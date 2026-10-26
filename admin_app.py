"""Compatibility entry point: serves the same unified app; open http://127.0.0.1:5001/admin."""
from webapp import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=False)
