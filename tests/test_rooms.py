# Copyright (c) 2026 Filip Marić. See LICENCE.
import app as myapp


def test_rooms(client, db):
    db.room(name="R1")
    db.room(name="Lab1", type="lab")

    r = client.get("/rooms")

    data = r.get_json()

    assert len(data) == 2

def test_rooms_filter(client, db):
    db.room(name="R1", type="lecture")
    db.room(name="Lab1", type="lab")

    r = client.get("/rooms?type=lab")

    data = r.get_json()

    assert len(data) == 1
    assert data[0]["name"] == "Lab1"


def test_rooms_include_display_metadata(client, db):
    db.room(name="R1", floor_wing="I sprat - sever", display_order=3)

    response = client.get("/rooms")

    assert response.get_json()[0]["floor_wing"] == "I sprat - sever"
    assert response.get_json()[0]["display_order"] == 3


def test_rooms_include_building_priority(client, db):
    db.building_location("A", 44.0, 20.0)
    db.room(name="R1", building_name="A")

    response = client.get("/rooms")

    assert response.get_json()[0]["building_priority"] == 100


def test_teacher_office_rooms_are_hidden_from_reservation_rooms(client, db):
    db.room(name="Teacher office", type="teacher_office")
    db.room(name="R1", type="lecture")

    response = client.get("/rooms")

    assert [room["name"] for room in response.get_json()] == ["R1"]


def test_rooms_rate_limit(client, db, monkeypatch):
    db.room(name="R1")
    monkeypatch.setitem(myapp.RATE_LIMITS, "rooms", (1, 60))

    assert client.get("/rooms").status_code == 200

    r = client.get("/rooms")
    assert r.status_code == 429
    assert r.get_json() == {"error": "Превише захтева. Покушајте поново касније."}


def test_occupancy_rate_limit(client, db, monkeypatch):
    monkeypatch.setitem(myapp.RATE_LIMITS, "occupancy", (1, 60))

    assert client.get("/occupancy?date=2026-03-09").status_code == 200

    r = client.get("/occupancy?date=2026-03-09")
    assert r.status_code == 429
    assert r.get_json() == {"error": "Превише захтева. Покушајте поново касније."}
