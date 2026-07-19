from flask import Flask, request, jsonify

app = Flask(__name__)

# In-memory storage
todos_list = []

@app.route("/todos", methods=["GET", "POST"])
def todos():
    if request.method == "GET":
        return jsonify(todos_list)
    else:
        todo = request.json.get("todo")
        if not todo:
            return jsonify({"error": "todo field is required"}), 400
        todos_list.append(todo)
        return jsonify({"message": "todo added", "todo": todo}), 201

@app.route("/todos/<int:id>", methods=["DELETE"])
def delete_todo(id):
    if id < 1 or id > len(todos_list):
        return jsonify({"error": "todo not found"}), 404
    deleted = todos_list.pop(id - 1)
    return jsonify({"message": "todo deleted", "todo": deleted})

if __name__ == "__main__":
    app.run(debug=True)