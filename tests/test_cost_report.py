"""Cost splits drive what gets cut, and an earlier version of this split blamed subagents for main-conversation work."""

import cost_report


def usage(read=0, write_1h=0, write_5m=0, output=0):
    return {"input_tokens": 0, "cache_read_input_tokens": read, "output_tokens": output,
            "cache_creation_input_tokens": write_1h + write_5m,
            "cache_creation": {"ephemeral_1h_input_tokens": write_1h, "ephemeral_5m_input_tokens": write_5m}}


def result(segment, read=0, write_1h=0, write_5m=0, output=0, model="claude-sonnet-5-5"):
    rates = cost_report.PRICES[model]
    cost = (write_5m * rates[1] + write_1h * rates[2] + read * rates[3] + output * rates[4]) / 1e6
    return {"type": "result", "usage": segment, "num_turns": 3,
            "modelUsage": {model: {"costUSD": cost, "inputTokens": 0, "outputTokens": output, "cacheReadInputTokens": read,
                                   "cacheCreationInputTokens": write_1h + write_5m}}}


def assistant(ident, stamp, read=0, parent=None):
    return {"type": "assistant", "parent_tool_use_id": parent, "timestamp": stamp,
            "message": {"id": ident, "usage": usage(read=read)}}


def test_a_run_sent_back_by_stop_is_not_mistaken_for_subagent_work():
    first, second = usage(read=900_000, write_1h=100_000, output=10_000), usage(read=100_000, write_1h=1_000, output=500)
    rows = [{**result(first, read=900_000, write_1h=100_000, output=10_000)},
            result(second, read=1_000_000, write_1h=101_000, output=10_500)]
    cost = cost_report.run_cost(rows)
    assert cost["segments"] == 2
    assert abs(cost["subagents"]) < 1e-9


def test_whole_run_minus_main_is_subagents():
    rows = [result(usage(read=1000, write_1h=1000, output=100), read=11_000, write_1h=1000, write_5m=2000, output=1100)]
    cost = cost_report.run_cost(rows)
    expected = (2000 * 2.5 + 10_000 * 0.1 + 1000 * 10) / 1e6
    assert abs(cost["subagents"] - expected) < 1e-9


def test_five_minute_price_only_touches_main_one_hour_writes():
    rows = [result(usage(read=1000, write_1h=1_000_000, output=100), read=1000, write_1h=1_000_000, write_5m=500_000, output=100)]
    cost = cost_report.run_cost(rows)
    assert abs(cost["total"] - cost["five_min"] - 1.5) < 1e-9  # $1.50 less per million on Sonnet, and subagent writes don't move
    assert cost["five_min_gaps"] == cost["five_min"]


def test_a_long_gap_writes_the_context_again_at_five_minutes():
    rows = [assistant("a", "2026-11-05T10:00:00Z", read=10),
            assistant("a", "2026-11-05T10:00:01Z", read=10),  # the same message, on a second row
            assistant("b", "2026-11-05T10:01:00Z", read=20),
            assistant("sub", "2026-11-05T10:03:00Z", read=9999, parent="tool"),  # a subagent's traffic doesn't refresh the main cache
            assistant("c", "2026-11-05T10:07:00Z", read=1_000_000),
            result(usage(read=1_000_030, write_1h=0), read=1_000_030)]
    cost = cost_report.run_cost(rows)
    assert cost["gaps_over"] == 1
    assert abs(cost["five_min_gaps"] - cost["five_min"] - 2.4) < 1e-9  # a million tokens at 2.5 instead of 0.1


def test_a_run_with_no_result_row_is_left_out_not_counted_as_free():
    assert cost_report.run_cost([assistant("a", "2026-11-05T10:00:00Z")]) is None


def test_collect_reads_both_trace_layouts(tmp_path):
    import gzip
    import json
    line = json.dumps(result(usage(read=1000), read=1000))
    graded = tmp_path / "graded" / "some-case" / "with-0"
    graded.mkdir(parents=True)
    (graded / "trace.jsonl").write_text(line)
    traces = tmp_path / "traces"
    traces.mkdir()
    with gzip.open(traces / "without-1.jsonl.gz", "wt") as handle:
        handle.write(line)
    runs = cost_report.collect(tmp_path)
    assert len(runs["some-case"]["with"]) == 1
    assert len(runs[tmp_path.name]["without"]) == 1


def test_shares_are_left_out_when_the_overhead_is_near_zero():
    extra = {"total": -0.1, "write": 0.3, "read": 0.5, "output": 0.2, "subagents": -1.1}
    line = cost_report.overhead_line(1, 4.0, extra)
    assert "1 case:" in line and "Too close to zero" in line and "%," not in line


def test_shares_add_up_on_a_real_overhead():
    extra = {"total": 1.0, "write": 0.5, "read": 0.2, "output": 0.3, "subagents": -0.0001}
    line = cost_report.overhead_line(7, 2.0, extra)
    assert "7 cases: +50% over no skill" in line
    assert "write 50%, read 20%, output 30%, subagents 0%" in line and "-0%" not in line
    assert "Share of the extra" in line


def test_a_cheaper_arm_gets_shares_of_a_saving():
    extra = {"total": -1.0, "write": 0.3, "read": 0.5, "output": 0.2, "subagents": -2.0}
    line = cost_report.overhead_line(1, 4.0, extra)
    assert "-25% over no skill" in line
    assert "Share of the saving: write -30%, read -50%, output -20%, subagents 200%" in line
