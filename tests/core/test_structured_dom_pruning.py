from chintu_backend.tools.browser.structured_dom import DOMParser


def test_playwright_snapshot_prunes_non_signal_nodes():
    parser = DOMParser()
    page_data = {
        "role": "WebArea",
        "name": "Example",
        "children": [
            {"role": "generic", "name": "", "children": []},
            {"role": "button", "name": "Create channel", "children": []},
            {"role": "link", "name": "View all channels", "children": []},
            {"role": "text", "name": "   ", "children": []},
            {"role": "heading", "name": "Channel setup", "children": []},
            {"role": "statictext", "name": "Click continue", "children": []},
            {"role": "generic", "name": "", "hidden": True, "children": []},
        ],
    }

    dom = parser.parse_from_playwright(page_data, url="https://example.com", title="Example")
    refs = list(dom.elements.keys())
    texts = " ".join(element.text.lower() for element in dom.elements.values())

    assert len(refs) > 0
    assert "create channel" in texts
    assert "view all channels" in texts
    assert "channel setup" in texts
    assert all("generic" not in ref for ref in refs)
