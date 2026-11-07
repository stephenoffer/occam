"""What occam's references most need to say, stated when it applies instead of held until the file is read.

Holds that only forced a read were 44 of 77 denials in recorded runs, each paying for a denied call, a read and a retry. Pointers
alone got references opened in 1 of 15 runs. Context added before an edit reaches the model and costs no turn, so the facts go there
and the file stays available for an agent that wants more.
"""

from __future__ import annotations  # the stock macOS python3 is 3.9

from scale_notes import TOOL

FACTS = {
    "security": ("Check authentication and authorization separately, and send every new route, batch, export and background job through the "
                 "same mechanism as existing paths. A missing credential, unset flag or failed check must deny. Parameterize queries. Retry only "
                 "what is safe to repeat: an effect that mustn't happen twice needs an idempotency key or a dedupe record committed with it. "
                 "Messages can repeat or arrive out of order, and workers can die mid-task, so decide what each failure point leaves behind."),
    "performance": ("State the workload as sizes, concurrency and limits, then find the stage that binds before tuning anything. Time isn't the only "
                    "thing that grows: check peak memory, queues, retries and fan-out, because the next stage may materialize everything. "
                    "Re-measure the whole path on the same input after a fix, and keep what the old shape gave for free, such as ordering. "
                    f"`{TOOL} bench --cmd \"... {{n}}\" --sizes 1000,10000` measures growth in fresh processes."),
    "design": ("Check that the name you'd install is the package the documentation means, that the API you need exists in the version you'd get, and "
               "its maintenance, license, advisories, transitive dependencies and install scripts. What the repository, standard library and "
               "installed dependencies already offer comes first, as long as its semantics really fit. "
               f"`{TOOL} deps --name pypi:NAME` asks the registry whether a package is real."),
}


def reference_note(name: str, why: str, path: str) -> str:
    return f"occam: {why}. {FACTS[name]} More is at {path}, if it would help."
