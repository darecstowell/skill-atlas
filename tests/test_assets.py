import json
import subprocess

from skill_atlas import assets


def tree(*paths):
    return {
        "tree": [{"type": "blob", "path": p} for p in paths] + [{"type": "tree", "path": "x.png"}]
    }


def test_images_filters():
    t = tree(
        "a.png",
        "assets/b.JPG",
        "c.jpeg",
        "d.webp",
        "e.gif",
        "f.avif",
        "logo.svg",
        "README.md",
        "vendor/v.png",
        "Tests/t.png",
        "x/testdata/t.png",
        "node_modules/n.png",
        "fixtures/f.png",
        "assets/Sponsors/s.png",
    )
    assert assets.images(t) == ["a.png", "assets/b.JPG", "c.jpeg", "d.webp", "e.gif", "f.avif"]


def test_images_cap():
    t = tree(*[f"i{n}.png" for n in range(assets.MAX_IMAGES + 10)])
    assert len(assets.images(t)) == assets.MAX_IMAGES


def test_meta_partial(monkeypatch):
    payload = {
        "data": {
            "r0": {
                "openGraphImageUrl": "https://og/x",
                "usesCustomOpenGraphImage": True,
                "description": None,
                "stargazerCount": 7,
                "owner": {"avatarUrl": "https://av/x"},
            },
            "r1": None,
        },
        "errors": [{"message": "not found"}],
    }

    def run(*a, **k):
        return subprocess.CompletedProcess(a, 1, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(assets.subprocess, "run", run)
    assert assets._meta(["o/a", "o/missing"]) == {
        "o/a": {
            "avatar": "https://av/x",
            "banner": "https://og/x",
            "custom_banner": True,
            "description": "",
            "stars": 7,
        }
    }


def test_meta_no_gh(monkeypatch):
    def run(*a, **k):
        raise OSError("no gh")

    monkeypatch.setattr(assets.subprocess, "run", run)
    assert assets._meta(["o/a"]) == {}


def test_fetch_caches(monkeypatch):
    assets._cache.clear()
    calls = {"meta": 0, "tree": 0}

    def meta(repos):
        calls["meta"] += 1
        return {"o/a": {"stars": 1}}

    def fetch_tree(repo, ref):
        calls["tree"] += 1
        return tree("a.png") if repo == "o/a" else None

    monkeypatch.setattr(assets, "_meta", meta)
    monkeypatch.setattr(assets, "fetch_tree", fetch_tree)
    first = assets.fetch(["o/a", "o/b"])
    assert first == {"o/a": {"stars": 1, "images": ["a.png"]}, "o/b": {"images": []}}
    assert assets.fetch(["o/a", "o/b"]) == first
    assert calls == {"meta": 1, "tree": 2}
    assets._cache.clear()
