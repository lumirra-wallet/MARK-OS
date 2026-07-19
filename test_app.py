import pytest
import json
from app import app


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def reset_todos():
    """Reset the todos list before each test."""
    from app import todos_list
    todos_list.clear()


def test_get_todos_empty(client):
    """Test GET /todos returns empty list initially."""
    response = client.get("/todos")
    assert response.status_code == 200
    assert response.get_json() == []


def test_post_todo(client):
    """Test POST /todos adds a new todo."""
    response = client.post(
        "/todos",
        data=json.dumps({"todo": "Buy groceries"}),
        content_type="application/json"
    )
    assert response.status_code == 201
    data = response.get_json()
    assert data["message"] == "todo added"
    assert data["todo"] == "Buy groceries"


def test_post_todo_missing_field(client):
    """Test POST /todos returns 400 when todo field is missing."""
    response = client.post(
        "/todos",
        data=json.dumps({}),
        content_type="application/json"
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["error"] == "todo field is required"


def test_get_todos_after_post(client):
    """Test GET /todos returns the added todo."""
    client.post(
        "/todos",
        data=json.dumps({"todo": "Learn Flask"}),
        content_type="application/json"
    )
    response = client.get("/todos")
    assert response.status_code == 200
    assert response.get_json() == ["Learn Flask"]


def test_delete_todo(client):
    """Test DELETE /todos/<id> deletes a todo."""
    client.post(
        "/todos",
        data=json.dumps({"todo": "Delete me"}),
        content_type="application/json"
    )
    response = client.delete("/todos/1")
    assert response.status_code == 200
    data = response.get_json()
    assert data["message"] == "todo deleted"
    assert data["todo"] == "Delete me"


def test_delete_todo_not_found(client):
    """Test DELETE /todos/<id> returns 404 for non-existent id."""
    response = client.delete("/todos/1")
    assert response.status_code == 404
    data = response.get_json()
    assert data["error"] == "todo not found"


def test_delete_todo_invalid_id(client):
    """Test DELETE /todos/<id> returns 404 for invalid id (out of bounds)."""
    client.post(
        "/todos",
        data=json.dumps({"todo": "Only one"}),
        content_type="application/json"
    )
    response = client.delete("/todos/5")
    assert response.status_code == 404
    data = response.get_json()
    assert data["error"] == "todo not found"


def test_delete_todo_zero_id(client):
    """Test DELETE /todos/<id> returns 404 for id=0."""
    response = client.delete("/todos/0")
    assert response.status_code == 404
    data = response.get_json()
    assert data["error"] == "todo not found"


def test_multiple_todos(client):
    """Test adding multiple todos and deleting one."""
    client.post(
        "/todos",
        data=json.dumps({"todo": "First"}),
        content_type="application/json"
    )
    client.post(
        "/todos",
        data=json.dumps({"todo": "Second"}),
        content_type="application/json"
    )
    client.post(
        "/todos",
        data=json.dumps({"todo": "Third"}),
        content_type="application/json"
    )
    
    # Delete the second todo (id=2)
    response = client.delete("/todos/2")
    assert response.status_code == 200
    assert response.get_json()["todo"] == "Second"
    
    # Verify remaining todos
    response = client.get("/todos")
    assert response.get_json() == ["First", "Third"]