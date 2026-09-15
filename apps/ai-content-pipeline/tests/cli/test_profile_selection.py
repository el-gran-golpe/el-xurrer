import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest
from typer.testing import CliRunner

from ai_content_pipeline.cli import main as cli_main
from ai_content_pipeline.cli.commands import fanvue, meta, pipeline, utils
from ai_content_pipeline.domain.types import Platform


all_commands = importlib.import_module("ai_content_pipeline.cli.commands.all")
runner = CliRunner()
PROFILE_COMMANDS = [
    ("all", "run_all"),
    ("all", "debug"),
    ("meta", "plan"),
    ("meta", "generate"),
    ("meta", "schedule"),
    ("fanvue", "plan"),
    ("fanvue", "generate"),
    ("fanvue", "schedule"),
    ("fanvue", "auth"),
]


@pytest.fixture
def profiles(monkeypatch):
    loaded = [
        SimpleNamespace(name="first_profile"),
        SimpleNamespace(name="second_profile"),
        SimpleNamespace(name="third_profile"),
    ]
    monkeypatch.setattr(utils.profile_manager, "_profiles", loaded)
    monkeypatch.setattr(
        utils.profile_manager,
        "_profiles_by_name",
        {profile.name: profile for profile in loaded},
    )
    return loaded


@pytest.mark.parametrize(
    ("indexes", "names", "selected_indexes"),
    [
        ([], None, [0, 1, 2]),
        ([0], None, [0]),
        ([2, 0], None, [2, 0]),
        ([], "second_profile", [1]),
        ([], " third_profile, first_profile ", [2, 0]),
        ([1], "first_profile", [1]),
        ([1], "", [1]),
    ],
)
def test_resolve_profiles_selects_requested_profiles(
    profiles, indexes, names, selected_indexes
):
    assert utils.resolve_profiles(indexes, names) == [
        profiles[index] for index in selected_indexes
    ]


@pytest.mark.parametrize(
    ("indexes", "names", "error"),
    [
        ([99], None, IndexError),
        ([0, 99], None, IndexError),
        ([99], "first_profile", IndexError),
        ([], "", KeyError),
        ([], " ", KeyError),
        ([], "missing_profile", KeyError),
        ([], "first_profile,missing_profile", KeyError),
    ],
)
def test_invalid_selection_never_falls_back_to_all(profiles, indexes, names, error):
    with pytest.raises(error):
        utils.resolve_profiles(indexes, names)


def test_resolve_profiles_returns_empty_when_none_are_loaded(monkeypatch):
    monkeypatch.setattr(utils.profile_manager, "_profiles", [])

    assert utils.resolve_profiles([], None) == []


@pytest.fixture
def command_spies(monkeypatch):
    spies = SimpleNamespace(
        plan=Mock(),
        generate=Mock(),
        schedule=AsyncMock(),
        execute_all=AsyncMock(),
        token_manager=Mock(),
        start_server=Mock(return_value=(None, 8000)),
        validate_auth=Mock(),
        cleanup_outputs=Mock(),
    )
    monkeypatch.setattr(cli_main, "get_gdrive_sync", Mock(return_value=Mock()))
    monkeypatch.setattr(utils.profile_manager, "load_profiles", Mock())
    monkeypatch.setattr(pipeline, "plan", spies.plan)
    monkeypatch.setattr(pipeline, "generate", spies.generate)
    monkeypatch.setattr(pipeline, "schedule", spies.schedule)
    monkeypatch.setattr(all_commands, "_execute_all", spies.execute_all)
    monkeypatch.setattr(all_commands, "validate_meta_profile_auth", spies.validate_auth)
    monkeypatch.setattr(all_commands, "_cleanup_local_outputs", spies.cleanup_outputs)
    monkeypatch.setattr(all_commands, "get_gdrive_sync", Mock(return_value=Mock()))
    monkeypatch.setattr(fanvue, "start_fastapi_server", spies.start_server)
    monkeypatch.setattr(fanvue, "FanvueTokenManager", spies.token_manager)
    return spies


@pytest.mark.parametrize(("group", "command"), PROFILE_COMMANDS)
@pytest.mark.parametrize(
    ("selectors", "selected_indexes"),
    [
        ([], [0, 1, 2]),
        (["-p", "2", "-p", "0"], [2, 0]),
        (["-n", "second_profile"], [1]),
    ],
)
def test_commands_run_for_all_or_selected_profiles(
    profiles, command_spies, group, command, selectors, selected_indexes
):
    result = runner.invoke(cli_main.app, [group, command, *selectors])

    assert result.exit_code == 0, result.output
    selected = [profiles[index] for index in selected_indexes]
    if group == "all":
        command_spies.execute_all.assert_awaited_once_with(selected, True, True, False)
    elif command == "auth":
        assert command_spies.token_manager.call_args_list == [
            call(profile.name) for profile in selected
        ]
        assert (
            command_spies.token_manager.return_value.authenticate_profile.call_args_list
            == [call(8000) for _ in selected]
        )
    else:
        platform = Platform.META if group == "meta" else Platform.FANVUE
        if command == "plan":
            command_spies.plan.assert_called_once_with(
                platform, selected, True, refresh_model_cache=False
            )
        elif command == "generate":
            command_spies.generate.assert_called_once_with(platform, selected)
        else:
            publisher = (
                meta.MetaPublisher if group == "meta" else fanvue.FanvueAPIPublisher
            )
            if group == "meta":
                command_spies.schedule.assert_awaited_once_with(
                    platform, selected, publisher, resume=False
                )
            else:
                command_spies.schedule.assert_awaited_once_with(
                    platform, selected, publisher
                )


@pytest.mark.parametrize(("group", "command"), PROFILE_COMMANDS)
@pytest.mark.parametrize(
    "selectors", [["-n", ""], ["-n", "missing_profile"], ["-p", "99"]]
)
def test_invalid_cli_selection_does_not_run_any_profiles(
    profiles, command_spies, group, command, selectors
):
    result = runner.invoke(cli_main.app, [group, command, *selectors])

    assert result.exit_code != 0
    assert isinstance(result.exception, (KeyError, IndexError))
    for spy in vars(command_spies).values():
        spy.assert_not_called()
