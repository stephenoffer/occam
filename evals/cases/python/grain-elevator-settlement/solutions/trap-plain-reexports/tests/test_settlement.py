import json
import pickle
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, call, patch
from urllib.error import URLError

import pytest

from grainbank import settlement, worker
from grainbank.settlement import (
    CheckpointError,
    FeedError,
    Grade,
    GradingError,
    Ledger,
    LedgerError,
    PricedTicket,
    SettlementCheckpoint,
    ticket_from_dict,
    ticket_to_dict,
)
from grainbank.taskapp import UnknownTask, app

FROZEN = datetime(2026, 11, 5, 8, 30, tzinfo=timezone.utc)


def load(**overrides):
    base = {
        "id": "T-1",
        "member": "M-1",
        "commodity": "corn",
        "gross_lb": 56000,
        "tare_lb": 28000,
        "moisture": "15.0",
        "test_weight": "57",
        "foreign_material": "0.5",
        "weighed_on": (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat(),
        "location": "north",
    }
    return ticket_from_dict({**base, **overrides})


def feed_response(payload):
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    response.__enter__.return_value = response
    return response


@pytest.fixture(autouse=True)
def clean_module_state():
    settlement.clear_price_cache()
    app.pending.clear()
    yield
    settlement.set_season("2026-fall")
    settlement.clear_price_cache()
    app.pending.clear()


# Grading


def test_dry_clean_load_pays_on_its_full_weight():
    assert settlement.net_bushels(load()) == Decimal("500.00")


def test_wet_load_shrinks():
    ticket = load(moisture="18.0")
    assert settlement.moisture_shrink_percent(ticket) == Decimal("4.2")
    assert settlement.net_bushels(ticket) == Decimal("479.00")


def test_foreign_material_is_docked_above_half_a_point():
    assert settlement.net_bushels(load(foreign_material="1.5")) == Decimal("495.00")


@pytest.mark.parametrize(
    "weight,grade",
    [("57", Grade.NO1), ("56", Grade.NO1), ("54.5", Grade.NO2), ("52", Grade.NO3), ("51.9", Grade.SAMPLE)],
)
def test_grade_follows_test_weight(weight, grade):
    assert settlement.grade_ticket(load(test_weight=weight)) is grade


def test_too_much_foreign_material_is_sample_grade():
    assert settlement.grade_ticket(load(foreign_material="3.1")) is Grade.SAMPLE


@pytest.mark.parametrize(
    "bad", [{"commodity": "rye"}, {"gross_lb": 100, "tare_lb": 100}, {"moisture": "41"}, {"test_weight": "0"}, {"foreign_material": "-1"}]
)
def test_impossible_tickets_are_refused(bad):
    with pytest.raises(GradingError):
        settlement.validate_ticket(load(**bad))


def test_ticket_survives_being_written_out_and_read_back():
    ticket = load(location="river")
    assert ticket_from_dict(ticket_to_dict(ticket)) == ticket


# Board feed


@patch("grainbank.board.urlopen")
def test_fetch_board_parses_prices(urlopen):
    urlopen.return_value = feed_response({"prices": {"corn": "4.35", "wheat": 5.5}})
    assert settlement.fetch_board() == {"corn": Decimal("4.35"), "wheat": Decimal("5.5")}


@patch("grainbank.board.send_alert")
@patch("grainbank.board.time.sleep")
@patch("grainbank.board.urlopen", side_effect=URLError("down"))
def test_feed_outage_retries_backs_off_and_alerts(urlopen, sleep, alert):
    with pytest.raises(FeedError):
        settlement.fetch_board()
    assert urlopen.call_count == 3
    assert sleep.call_args_list == [call(2.0), call(4.0)]
    alert.assert_called_once()
    assert alert.call_args.args[0] == "board feed down"


@patch("grainbank.board.send_alert")
@patch("grainbank.board.time.sleep")
@patch("grainbank.board.urlopen", side_effect=URLError("down"))
def test_retry_count_can_be_turned_down(urlopen, sleep, alert):
    with patch("grainbank.board.MAX_FEED_RETRIES", 1):
        with pytest.raises(FeedError):
            settlement.fetch_board()
    assert urlopen.call_count == 1
    sleep.assert_not_called()


@patch("grainbank.board.urlopen")
def test_board_price_only_fetches_once(urlopen):
    urlopen.return_value = feed_response({"prices": {"corn": "4.35"}})
    assert settlement.board_price("corn") == Decimal("4.35")
    assert settlement.board_price("corn") == Decimal("4.35")
    assert urlopen.call_count == 1


def test_board_price_answers_from_the_cache():
    with patch.dict("grainbank.board._PRICE_CACHE", {"corn": Decimal("4.10")}, clear=True):
        assert settlement.board_price("corn") == Decimal("4.10")


@patch("grainbank.board.urlopen")
def test_refresh_replaces_the_cache(urlopen):
    urlopen.return_value = feed_response({"prices": {"corn": "4.00"}})
    assert settlement.refresh_board_prices() == {"corn": "4.00"}
    urlopen.return_value = feed_response({"prices": {"corn": "4.50"}})
    assert settlement.refresh_board_prices() == {"corn": "4.50"}


# Alerts


@patch("grainbank.alerts.utcnow", return_value=FROZEN)
@patch("grainbank.alerts.urlopen")
def test_alert_posts_json(urlopen, _now):
    assert settlement.send_alert("hello", "there") is True
    request = urlopen.call_args.args[0]
    assert json.loads(request.data) == {"subject": "hello", "details": "there", "sent_at": FROZEN.isoformat()}


@patch("grainbank.alerts.urlopen", side_effect=URLError("down"))
def test_failed_alert_never_stops_the_work(_urlopen):
    assert settlement.send_alert("hello") is False


# Pricing


def test_price_with_the_board_given():
    priced = settlement.price_ticket(load(), Ledger(), Decimal("4.00"))
    assert priced.price_per_bushel == Decimal("3.8200")
    assert priced.amount == Decimal("1910.00")
    assert priced.grade is Grade.NO1


@patch("grainbank.pricing.board_price", return_value=Decimal("5.00"))
def test_price_reads_the_board_when_none_is_given(board_price):
    priced = settlement.price_ticket(load(), Ledger())
    board_price.assert_called_once_with("corn")
    assert priced.board == Decimal("5.00")


def test_wet_low_grade_load_pays_less():
    priced = settlement.price_ticket(load(moisture="18.0", test_weight="53"), Ledger(), Decimal("4.00"))
    assert priced.drying == Decimal("0.0750")
    assert priced.grade_discount == Decimal("0.08")
    assert priced.price_per_bushel == Decimal("3.6650")


def test_patronage_depends_on_what_has_been_delivered():
    ledger = Ledger()
    ledger.post("M-1", Decimal("0"), Decimal("20000"), "opening")
    assert settlement.price_ticket(load(), ledger, Decimal("4.00")).patronage == Decimal("0.1200")


def test_unknown_location_is_refused():
    with pytest.raises(GradingError):
        settlement.price_ticket(load(location="moon"), Ledger(), Decimal("4.00"))


# Ledger


@patch("grainbank.ledger.utcnow", return_value=FROZEN)
def test_postings_are_stamped(_now):
    assert Ledger().post("M-1", Decimal("1.005")).posted_at == FROZEN


def test_a_ticket_settles_once():
    ledger = Ledger()
    ledger.post_settlement(load(), Decimal("4.00"))
    with pytest.raises(LedgerError):
        ledger.post_settlement(load(), Decimal("4.00"))
    assert ledger.balance("M-1") == Decimal("1910.00")


@patch("grainbank.ledger.price_ticket")
def test_settlement_posts_what_pricing_says(price_ticket):
    price_ticket.return_value = PricedTicket(
        "T-1", "M-1", "corn", Grade.NO2, Decimal("10"), Decimal("4"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("4"), Decimal("40.00")
    )
    ledger = Ledger()
    ledger.post_settlement(load())
    assert ledger.balance("M-1") == Decimal("40.00")
    assert ledger.entries[0].memo == "corn No. 2"


@patch("grainbank.ledger.Ledger.post")
def test_settlement_goes_through_post(post):
    Ledger().post_settlement(load(), Decimal("4.00"))
    post.assert_called_once()


def test_reversal_keeps_the_record():
    ledger = Ledger()
    ledger.post_settlement(load(), Decimal("4.00"))
    ledger.reverse("T-1", "wrong member")
    assert ledger.balance("M-1") == Decimal("0.00")
    assert len(ledger.entries) == 2
    with pytest.raises(LedgerError):
        ledger.reverse("T-1", "again")
    with pytest.raises(LedgerError):
        ledger.reverse("T-404", "never settled")


def test_ledger_round_trips(tmp_path):
    ledger = Ledger()
    ledger.post_settlement(load(), Decimal("4.00"))
    path = tmp_path / "ledger.json"
    ledger.save(path)
    assert Ledger.load(path).entries == ledger.entries
    assert Ledger.load(tmp_path / "missing.json").entries == []


# Statements


@patch("grainbank.statements.utcnow", return_value=FROZEN)
def test_statement_text(_now):
    ledger = Ledger()
    ledger.post_settlement(load(), Decimal("4.00"))
    text = settlement.render_statement("M-1", ledger)
    assert "Season: Fall 2026" in text
    assert "Generated: 2026-11-05" in text
    assert text.endswith("Total bushels: 500.00\nBalance: 1910.00\n")


def test_statements_follow_the_season():
    settlement.set_season("2027-spring")
    assert settlement.statement_filename("M-1") == "2027-spring-M-1.txt"
    assert settlement.season_label() == "Spring 2027"
    with pytest.raises(ValueError):
        settlement.set_season("next year")


# Checkpoints


def test_checkpoint_survives_pickling_and_finishes_the_close():
    checkpoint = SettlementCheckpoint([load(id="T-1"), load(id="T-2"), load(id="T-3")])
    ledger = Ledger()
    checkpoint.results.append(settlement.settle_ticket(checkpoint.tickets[0], ledger, Decimal("4.00")))
    checkpoint.cursor.advance("T-1")
    again = pickle.loads(pickle.dumps(checkpoint, protocol=2))
    assert [ticket.id for ticket in again.remaining()] == ["T-2", "T-3"]
    assert [priced.ticket_id for priced in again.resume(ledger, Decimal("4.00"))] == ["T-2", "T-3"]
    assert again.remaining() == []
    assert again.results[0].grade is Grade.NO1


@patch("grainbank.checkpoints.settle_ticket")
def test_resume_goes_through_settle_ticket(settle_ticket):
    SettlementCheckpoint([load()]).resume(Ledger(), Decimal("4.00"))
    settle_ticket.assert_called_once()


@patch("grainbank.checkpoints.utcnow", return_value=FROZEN)
def test_saved_checkpoint_is_stamped(_now, tmp_path):
    path = tmp_path / "close.pkl"
    settlement.save_checkpoint(SettlementCheckpoint([load()]), path)
    assert settlement.load_checkpoint(path).saved_at == FROZEN


def test_other_pickles_are_refused(tmp_path):
    path = tmp_path / "other.pkl"
    path.write_bytes(pickle.dumps({"not": "a checkpoint"}))
    with pytest.raises(CheckpointError):
        settlement.load_checkpoint(path)
    with pytest.raises(CheckpointError):
        settlement.load_checkpoint(tmp_path / "missing.pkl")


def test_version_two_state_is_upgraded():
    checkpoint = SettlementCheckpoint.__new__(SettlementCheckpoint)
    checkpoint.__setstate__({"version": 2, "tickets": [load()], "position": 1, "results": [], "saved_at": None})
    assert checkpoint.cursor.index == 1
    assert checkpoint.season == "2026-fall"
    assert checkpoint.remaining() == []


# Jobs


@patch("grainbank.settling.send_alert")
@patch("grainbank.clock.utcnow", return_value=FROZEN)
def test_stale_ticket_alerts_but_settles(_now, alert):
    ledger = Ledger()
    old = load(weighed_on=(FROZEN.date() - timedelta(days=11)).isoformat())
    settlement.settle_ticket(old, ledger, Decimal("4.00"))
    alert.assert_called_once()
    assert ledger.has_ticket("T-1")


@patch("grainbank.settling.send_alert")
@patch("grainbank.clock.utcnow", return_value=FROZEN)
def test_fresh_ticket_does_not_alert(_now, alert):
    settlement.settle_ticket(load(weighed_on=FROZEN.date().isoformat()), Ledger(), Decimal("4.00"))
    alert.assert_not_called()


def test_one_bad_ticket_does_not_hold_up_the_rest():
    settled, failures = settlement.settle_batch([load(id="T-1"), load(id="T-2", commodity="rye"), load(id="T-3")], Ledger(), Decimal("4.00"))
    assert [priced.ticket_id for priced in settled] == ["T-1", "T-3"]
    assert list(failures) == ["T-2"]


def write_tickets(tmp_path, *tickets):
    path = tmp_path / "tickets.json"
    path.write_text(json.dumps([ticket_to_dict(ticket) for ticket in tickets]))
    return str(path)


@patch("grainbank.jobs.app.send_task")
@patch("grainbank.jobs.send_alert")
@patch("grainbank.pricing.board_price", return_value=Decimal("4.00"))
def test_nightly_close_settles_and_queues_statements(_board, alert, send_task, tmp_path):
    tickets = write_tickets(tmp_path, load(id="T-1"), load(id="T-2", member="M-2"), load(id="T-3", commodity="rye"))
    summary = settlement.nightly_close(tickets, str(tmp_path / "ledger.json"), str(tmp_path))
    assert summary["settled"] == ["T-1", "T-2"]
    assert summary["failed"] == ["T-3"]
    assert summary["amount"] == "3820.00"
    assert send_task.call_count == 2
    alert.assert_called_once()


@patch("grainbank.jobs.app.send_task")
@patch("grainbank.pricing.board_price", return_value=Decimal("4.00"))
def test_nightly_close_can_leave_a_checkpoint(_board, _send_task, tmp_path):
    tickets = write_tickets(tmp_path, load(id="T-1"), load(id="T-2"))
    settlement.nightly_close(tickets, str(tmp_path / "ledger.json"), str(tmp_path), str(tmp_path / "close.pkl"))
    checkpoint = settlement.load_checkpoint(tmp_path / "close.pkl")
    assert checkpoint.remaining() == []
    assert checkpoint.cursor.last_ticket == "T-2"


def test_send_statement_writes_the_file(tmp_path):
    ledger = Ledger()
    ledger.post_settlement(load(), Decimal("4.00"))
    path = tmp_path / "ledger.json"
    ledger.save(path)
    assert settlement.send_statement("M-1", str(path), str(tmp_path)) == "2026-fall-M-1.txt"
    assert "Balance: 1910.00" in (tmp_path / "2026-fall-M-1.txt").read_text()


@patch("grainbank.jobs.send_alert")
def test_reconcile_alerts_on_a_mismatch(alert, tmp_path):
    ledger = Ledger()
    ledger.post("M-1", Decimal("5.00"))
    path = tmp_path / "ledger.json"
    ledger.save(path)
    assert settlement.reconcile_member("M-1", str(path), "5.00")["matches"] is True
    alert.assert_not_called()
    assert settlement.reconcile_member("M-1", str(path), "6.00")["matches"] is False
    alert.assert_called_once()


def test_reverse_task_saves_the_ledger(tmp_path):
    ledger = Ledger()
    ledger.post_settlement(load(), Decimal("4.00"))
    path = tmp_path / "ledger.json"
    ledger.save(path)
    assert settlement.reverse_ticket("T-1", "oops", str(path)) == {"member": "M-1", "amount": "-1910.00"}
    assert Ledger.load(path).balance("M-1") == Decimal("0.00")


def test_tasks_are_registered_under_their_own_names():
    for task in (settlement.nightly_close, settlement.send_statement, settlement.refresh_board_prices,
                 settlement.reconcile_member, settlement.reverse_ticket):
        assert app.tasks[task.name] is task


def test_delay_queues_by_name_and_drain_runs_it(tmp_path):
    settlement.send_statement.delay("M-1", str(tmp_path / "ledger.json"), str(tmp_path))
    assert app.drain() == [{"task": settlement.send_statement.name, "result": "2026-fall-M-1.txt"}]


def test_unknown_task_is_refused():
    with pytest.raises(UnknownTask):
        app.send_task("no.such.task")


def test_worker_lists_and_runs_tasks(tmp_path, capsys):
    assert worker.main(["--list"]) == 0
    assert settlement.send_statement.name in capsys.readouterr().out.split()
    args = json.dumps(["M-1", str(tmp_path / "ledger.json"), str(tmp_path)])
    assert worker.main(["run", settlement.send_statement.name, "--args", args]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "2026-fall-M-1.txt"
    assert worker.main(["run", "no.such.task"]) == 1
