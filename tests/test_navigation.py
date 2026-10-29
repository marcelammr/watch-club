from app.navigation import href_path, internal_href


def test_internal_href_keeps_same_host_path_and_query():
    assert internal_href("http://testserver/clubs/3?aba=assistindo", "testserver") == "/clubs/3?aba=assistindo"
    assert internal_href("/conta", "testserver") == "/conta"
    assert href_path("/clubs/3?aba=assistindo") == "/clubs/3"


def test_internal_href_rejects_external_and_malformed_targets():
    assert internal_href("https://evil.example/clubs/1", "testserver") == ""
    assert internal_href("//evil.example/clubs/1", "testserver") == ""
    assert internal_href("javascript:alert(1)", "testserver") == ""
    assert internal_href("https://testserver.evil.example/", "testserver") == ""
    assert internal_href("/../../etc/passwd", "testserver") == ""
    assert internal_href("", "testserver") == ""
    assert internal_href(None, "testserver") == ""
