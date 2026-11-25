from __future__ import annotations

import argparse
import json
import math

import pytest

from foundation_assistant import tribute_cycle as mod
from foundation_assistant.tribute_loop import Stop
from foundation_assistant.tribute_loop_vision import RepairView
from foundation_assistant.tribute_ui import params


class Game:
    def __init__(self, ap, *, cap=300, stall_refill=0, repair_available=False, completion="victory_mail"):
        self.ap, self.cap = ap, cap
        self.now = 0.0
        self.stall_refill = stall_refill
        self.actions = []
        self.rounds = 0
        self.repair_available = repair_available
        self.completion = completion

    def read_action_points(self):
        return self.ap, self.cap

    def refill(self, allow_use):
        self.now += self.stall_refill
        if not allow_use():
            return False
        self.actions.append("refill")
        self.ap += math.ceil((300 - self.ap) / 100) * 100
        return True

    def rally(self, options):
        self.actions.append("rally")
        self.rounds += 1
        self.now += 180
        self.ap -= 30
        return self.completion

    def repair(self):
        if self.repair_available:
            self.actions.append("repair")
        return self.repair_available


def simulate(game, *, hours=None, batch=8, finish=lambda: False, repair=True, total=None, strict_count=False):
    events = []
    options = mod.CycleOptions("Test captain", hours=hours, batch_size=batch, repair_after_rally=repair,
                               total_rallies=total, strict_count=strict_count)
    runner = mod.CycleRunner(game, options, emit=lambda e, **fields: events.append((e, fields)), finish_requested=finish,
                             clock=lambda: game.now)
    return runner.run(), events


@pytest.mark.parametrize("start", [300, 311])
def test_at_or_above_cap_skips_the_first_refill_and_runs_all_eight(start):
    game = Game(start)
    summary, events = simulate(game, hours=0.4)
    assert game.actions == ["rally"] * 8
    assert summary.reason == "time_limit" and summary.batches == 1
    assert summary.rallies == 8 and summary.ap == start - 240
    assert any(e == "refill_skipped" for e, _ in events)


def test_continuous_repeats_full_batches_then_finishes_when_requested():
    game = Game(11)
    summary, _ = simulate(game, finish=lambda: game.rounds == 16)
    assert game.actions == (["refill"] + ["rally"] * 8) * 2
    assert summary.reason == "requested" and summary.batches == 2
    assert summary.rallies == 16 and summary.refills == 2 and summary.ap == 131


@pytest.mark.parametrize(("total", "sizes", "ap"), [(8, [8], 71), (11, [8, 3], 281)])
def test_total_is_across_batches_and_does_not_refill_after_the_limit(total, sizes, ap):
    game = Game(311, repair_available=True, completion="repair_icon")
    summary, events = simulate(game, total=total)
    assert summary.reason == "count_limit" and summary.rallies == summary.repairs == total
    assert summary.ap == ap and summary.cleanup == 0 and summary.batches == 1
    assert game.actions[-2:] == ["rally", "repair"]
    assert game.actions.count("refill") == len(sizes) - 1
    assert [fields["size"] for name, fields in events if name == "batch_started"] == sizes
    assert ("count_reached", {"target": total}) in events


def test_count_stop_allows_only_necessary_ap_cleanup_by_default():
    game = Game(373)
    summary, events = simulate(game, total=1)
    assert summary.reason == "count_limit" and summary.rallies == 3
    assert summary.cleanup == 2 and summary.ap == 283
    assert game.actions == ["rally"] * 3
    assert dict(events)["count_reached"]["target"] == 1
    assert sum(k == "batch_started" for k, _ in events) == 1


def test_strict_count_never_sends_an_extra_rally_at_exactly_full_ap():
    game = Game(330, repair_available=True)
    summary, _ = simulate(game, total=1, strict_count=True)
    assert summary.reason == "count_limit" and summary.rallies == summary.repairs == 1
    assert summary.cleanup == 0 and summary.ap == 300
    assert game.actions == ["rally", "repair"]


def test_f9_cleanup_still_respects_a_strict_count_ceiling():
    game = Game(373)
    summary, _ = simulate(game, total=2, strict_count=True, finish=lambda: game.rounds == 1)
    assert summary.reason == "requested" and summary.rallies == 2
    assert summary.cleanup == 1 and summary.ap == 313 and game.actions == ["rally"] * 2


def test_timer_only_lets_the_last_in_progress_rally_finish_if_already_below_cap():
    game = Game(311)
    summary, _ = simulate(game, hours=0.01)
    assert game.actions == ["rally"]
    assert summary.rallies == 1 and summary.cleanup == 0 and summary.ap == 281


def test_timer_cleanup_never_refills_and_does_not_stop_at_exactly_300():
    game = Game(390)
    summary, events = simulate(game, hours=0.01)
    assert game.actions == ["rally"] * 4
    assert summary.batches == 0 and summary.cleanup == 3 and summary.ap == 270
    assert len([e for e, _ in events if e == "cleanup_round"]) == 3


def test_repairs_each_confirmed_round_including_cleanup_rounds():
    game = Game(390, repair_available=True, completion="repair_icon")
    summary, events = simulate(game, hours=0.01)
    assert game.actions == ["rally", "repair"] * 4
    assert summary.repairs == 4 and summary.ap == 270
    assert all(fields["completion"] == "repair_icon" for key, fields in events if key == "round_confirmed")


def test_repair_can_be_disabled_without_changing_battle_completion():
    game = Game(311, repair_available=True, completion="repair_icon")
    summary, events = simulate(game, hours=0.01, repair=False)
    assert game.actions == ["rally"] and summary.repairs == 0 and summary.rallies == 1
    assert dict(events)["round_confirmed"]["completion"] == "repair_icon"


def test_unverified_repair_stops_before_the_next_rally(monkeypatch):
    game = Game(311)
    def repair():
        game.actions.append("repair")
        raise Stop("repair prompt not cleared")
    monkeypatch.setattr(game, "repair", repair)
    with pytest.raises(Stop, match="not cleared"):
        simulate(game)
    assert game.actions == ["rally", "repair"]


def test_if_timer_ends_during_refill_navigation_the_potion_click_is_not_sent():
    game = Game(212, stall_refill=40)
    summary, _ = simulate(game, hours=0.01)
    assert not game.actions and summary.ap == 212 and summary.refills == 0


def test_graceful_stop_at_full_ap_keeps_only_the_necessary_drain_rallies():
    game = Game(300)
    summary, _ = simulate(game, finish=lambda: True)
    assert game.actions == ["rally"]
    assert summary.reason == "requested" and summary.cleanup == 1 and summary.ap == 270


def test_unconfirmed_result_stops_the_batch_without_refill_or_more_clicks(monkeypatch):
    game = Game(311)
    def fail(_):
        game.actions.append("rally")
        raise Stop("report not verified")
    monkeypatch.setattr(game, "rally", fail)
    with pytest.raises(Stop, match="report not verified"):
        simulate(game)
    assert game.actions == ["rally"]


@pytest.mark.parametrize("readback", [(270, 300), (240, 300)])
@pytest.mark.parametrize(("error_type", "retry_event"), [
    (mod.RallySetupNotOpened, "setup_retry"),
    (mod.RallyTargetNotFound, "target_retry"),
])
def test_preconfirm_retry_requires_identical_ap_readback(readback, error_type, retry_event):
    class LoopProbe:
        tries = 0
        readings = iter([(270, 300), readback])

        def read_action_points(self):
            return next(self.readings)

        def wait(self, *_):
            return RepairView(None)

        def start(self, _level, *, preview):
            assert not preview
            self.tries += 1
            if self.tries == 1:
                raise error_type("returned to star map")
            return 123

        def wait_battle_end(self, *_args, **_kw):
            return "victory_mail"

    events = []
    loop = LoopProbe()
    game = mod.LiveCycleGame(loop, lambda event, **_: events.append(event))
    game.read_action_points()
    if readback == (270, 300):
        assert game.rally(mod.CycleOptions("Test captain")) == "victory_mail"
        assert loop.tries == 2 and events == [retry_event, "round_submitted"]
    else:
        with pytest.raises(mod.CycleError) as error:
            game.rally(mod.CycleOptions("Test captain"))
        assert error.value.code == "setup_retry_ap_changed"
        assert loop.tries == 1 and not events


def test_unknown_cap_blocks_resource_actions():
    game = Game(300, cap=400)
    with pytest.raises(mod.CycleError) as error:
        simulate(game)
    assert error.value.code == "unknown_capacity" and not game.actions


def test_no_ap_decrease_does_not_repeat_cleanup_forever(monkeypatch):
    game = Game(311)
    monkeypatch.setattr(game, "rally", lambda _: game.actions.append("rally") or "victory_mail")
    with pytest.raises(mod.CycleError) as error:
        simulate(game, finish=lambda: True)
    assert error.value.code == "no_ap_decrease" and game.actions == ["rally"]


def test_cli_plan_never_launches_game(monkeypatch, capsys):
    parser = argparse.ArgumentParser()
    mod.add_parser(parser.add_subparsers())
    monkeypatch.setattr(mod, "_live", lambda *_: pytest.fail("plan touched the game"))
    args = parser.parse_args(["tribute-cycle", "--captain", "Test name", "--hours", "1.5"])
    assert args.func(args) == 0
    assert json.loads(capsys.readouterr().out) == {"mode": "plan", "size": [1920, 1080], "action_point_cap": 300,
                                                "level": 3, "batch_size": 8, "hours": 1.5,
                                                "repair_after_rally": True, "final_ap_below": 300}


def test_cli_count_plan_and_conflicting_modes(monkeypatch, capsys):
    parser = argparse.ArgumentParser()
    mod.add_parser(parser.add_subparsers())
    monkeypatch.setattr(mod, "_live", lambda *_: pytest.fail("plan touched the game"))
    prefix = ["tribute-cycle", "--captain", "Test name", "--total-rallies", "12"]
    args = parser.parse_args([*prefix, "--strict-count"])
    assert args.func(args) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["total_rallies"] == 12 and plan["strict_count"] and plan["hours"] is None
    with pytest.raises(SystemExit, match="2"):
        parser.parse_args([*prefix, "--hours", "1"])


def test_strict_full_ap_stop_is_reported_with_readback_not_normal_completion(monkeypatch, tmp_path):
    parser = argparse.ArgumentParser()
    mod.add_parser(parser.add_subparsers())
    monkeypatch.setattr(mod, "_live", lambda *_: mod.CycleSummary("count_limit", 343, 300, 1, 0, 0, 0, 190))
    path = tmp_path / "events.jsonl"
    args = parser.parse_args(["tribute-cycle", "--captain", "Test name", "--execute", "--event-log", str(path),
                              "--total-rallies", "1", "--strict-count"])
    args.profile = "foundation"
    assert args.func(args) == 2
    _, final = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert (final["event"], final["code"], final["rallies"], final["ap"]) == ("stopped", "count_limit_full_ap", 1, 343)


def test_worker_done_event_contains_verified_ap_and_log_is_not_overwritten(monkeypatch, tmp_path):
    parser = argparse.ArgumentParser()
    mod.add_parser(parser.add_subparsers())
    monkeypatch.setattr(mod, "_live", lambda *_: mod.CycleSummary("requested", 281, 300, 1, 0, 0, 1, 190))
    path = tmp_path / "events.jsonl"
    args = parser.parse_args(["tribute-cycle", "--captain", "Test name", "--execute", "--event-log", str(path)])
    args.profile = "foundation"
    assert args.func(args) == 0
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [e["event"] for e in events] == ["preparing", "finished"] and events[-1]["ap"] == 281
    with pytest.raises(FileExistsError):
        args.func(args)


def test_ui_parameter_validation_and_continuous_ignores_hidden_duration():
    fields = dict(captain=" Test captain ", level="3", batch="8", mode="continuous", hours="unused",
                  timeout="480", launch="")
    options = params(**fields)
    assert options.captain == "Test captain" and options.hours is None and options.batch_size == 8
    assert options.repair_after_rally
    assert "--no-repair-after-rally" in params(**fields, repair_after_rally=False).arguments()
    for changed, expected in (({"mode": "timed"}, "invalid_hours"), ({"level": "1.5"}, "invalid_level"),
                              ({"batch": "11"}, "invalid_batch"), ({"captain": "[CLAN] Test"}, "invalid_captain")):
        with pytest.raises(mod.CycleError) as error:
            params(**(fields | changed))
        assert error.value.code == expected


def test_ui_count_mode_validates_active_field_and_passes_strict_flag():
    fields = dict(captain="Test captain", level="3", batch="8", mode="count", hours="unused", timeout="480", launch="")
    options = params(**fields, total_rallies="12", strict_count=True)
    assert options.total_rallies == 12 and options.hours is None and options.strict_count
    assert options.arguments()[-3:] == ["--total-rallies", "12", "--strict-count"]
    for invalid in ("", "0", "1.5", str(mod.MAX_TOTAL_RALLIES + 1)):
        with pytest.raises(mod.CycleError) as error:
            params(**fields, total_rallies=invalid)
        assert error.value.code == "invalid_total_rallies"
