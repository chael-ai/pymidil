# {{cookiecutter.project_name}}

{{cookiecutter.project_short_description}}

Created by {{cookiecutter.author_name}} using MIDIL CLI.

## Features

- FastAPI web framework
- MIDIL SDK integration
- Health check endpoint
- Hot reload for development

## Getting Started

### Prerequisites

- Python {{cookiecutter.python_version}}+
- pip or poetry

### Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the application:
   ```bash
   python main.py
   ```

   Or using the MIDIL CLI:
   ```bash
   midil launch
   ```

3. Visit http://localhost:8000 to see your app running!

## API Endpoints

- `GET /` - Welcome message
- `GET /health` - Health check

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov={{cookiecutter.project_slug}}

# Using MIDIL CLI
midil test --coverage
```

### Code Formatting

```bash
# Format code
black .
ruff check --fix .
```

{% if cookiecutter.include_docker == "y" %}
## Docker

Build and run with Docker:

```bash
# Build image
docker build -t {{cookiecutter.project_slug}} .

# Run container
docker run -p 8000:8000 {{cookiecutter.project_slug}}
```
{% endif %}

## License

{% if cookiecutter.license is defined and cookiecutter.license != "None" %}
This project is licensed under the {{cookiecutter.license}} License.
{% else %}
This project is not licensed.
{% endif %}

## Author

{{cookiecutter.author_name}} ({{cookiecutter.author_email}})
