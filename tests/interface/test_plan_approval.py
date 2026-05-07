"""Interactive plan approval prompt tests."""


class FakeConsole:
    def __init__(self, inputs):
        self.inputs = list(inputs)
        self.printed = []
        self.prompts = []

    def print(self, *args, **kwargs):
        self.printed.append((args, kwargs))

    def input(self, prompt):
        self.prompts.append(prompt)
        if not self.inputs:
            raise EOFError
        return self.inputs.pop(0)


def test_plan_approval_confirm_executes_plan():
    from forgeagent.interface.plan_approval import build_plan_approval_fn

    console = FakeConsole(["y"])
    approval = build_plan_approval_fn(console)

    assert _run(approval("line1\nline2")) == {"choice": "execute"}
    assert console.prompts == ["  Proceed with this plan? [y/N]: "]


def test_plan_approval_yes_executes_plan():
    from forgeagent.interface.plan_approval import build_plan_approval_fn

    approval = build_plan_approval_fn(FakeConsole(["yes"]))

    assert _run(approval("plan")) == {"choice": "execute"}


def test_plan_approval_decline_keeps_planning():
    from forgeagent.interface.plan_approval import build_plan_approval_fn

    approval = build_plan_approval_fn(FakeConsole(["n"]))

    assert _run(approval("plan")) == {
        "choice": "keep-planning",
        "feedback": "User chose not to execute the plan.",
    }


def test_plan_approval_default_keeps_planning():
    from forgeagent.interface.plan_approval import build_plan_approval_fn

    approval = build_plan_approval_fn(FakeConsole([""]))

    assert _run(approval("plan")) == {
        "choice": "keep-planning",
        "feedback": "User chose not to execute the plan.",
    }


def test_plan_approval_invalid_answer_reprompts():
    from forgeagent.interface.plan_approval import build_plan_approval_fn

    console = FakeConsole(["maybe", "y"])
    approval = build_plan_approval_fn(console)

    assert _run(approval("plan")) == {"choice": "execute"}
    assert any("Please enter y or n" in str(args[0]) for args, _ in console.printed if args)


def _run(coro):
    import asyncio

    return asyncio.run(coro)
