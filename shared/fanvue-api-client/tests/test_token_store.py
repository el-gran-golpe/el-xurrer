from fanvue_api_client.token_store import FanvueTokenStore


def test_token_store_uses_profile_resource_token_path(tmp_path) -> None:
    store = FanvueTokenStore("laura_vigne", resources_root=tmp_path)

    assert store.token_path == tmp_path / "laura_vigne" / "fanvue" / "tokens.json"
