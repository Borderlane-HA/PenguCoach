from pengucoach.garmin.gateway.read_only import GarminReadOnlyGateway


def test_gateway_does_not_expose_mutations():
    public = {name for name in dir(GarminReadOnlyGateway) if not name.startswith("_")}
    forbidden_prefixes = ("set_", "upload_", "delete_", "create_", "schedule_", "add_", "update_")
    assert not any(name.startswith(forbidden_prefixes) for name in public)
    assert "get_user_summary" in public
    assert "download_activity_fit" in public
