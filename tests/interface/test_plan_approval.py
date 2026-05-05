"""Interactive plan approval prompt tests."""


class FakeConsole:
    def __init__(self, inputs):
        self.inputs = list(inputs)
        self.printed = []

    def print(self, *args, **kwargs):
        self.printed.append((args, kwargs))

    def input(self, _prompt):
        if not self.inputs:
            raise EOFError
        return self.inputs.pop(0)


def test_plan_approval_choice_clear_and_execute():
    from forgeagent.interface.plan_approval import build_plan_approval_fn

    approval = build_plan_approval_fn(FakeConsole(["1"]))

    assert _run(approval("line1\nline2")) == {"choice": "clear-and-execute"}


def test_plan_approval_choice_manual_execute():
    from forgeagent.interface.plan_approval import build_plan_approval_fn

    approval = build_plan_approval_fn(FakeConsole(["3"]))

    assert _run(approval("plan")) == {"choice": "manual-execute"}


def test_plan_approval_choice_keep_planning_collects_feedback():
    from forgeagent.interface.plan_approval import build_plan_approval_fn

    approval = build_plan_approval_fn(FakeConsole(["4", "more tests"]))

    assert _run(approval("plan")) == {
        "choice": "keep-planning",
        "feedback": "more tests",
    }


def test_plan_approval_invalid_choice_reprompts():
    from forgeagent.interface.plan_approval import build_plan_approval_fn

    console = FakeConsole(["bad", "2"])
    approval = build_plan_approval_fn(console)

    assert _run(approval("plan")) == {"choice": "execute"}
    assert any("Invalid choice" in str(args[0]) for args, _ in console.printed if args)


def _run(coro):
    import asyncio

    return asyncio.run(coro)
