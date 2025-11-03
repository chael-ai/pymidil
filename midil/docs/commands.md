---
slug: /cli/commands/init
title: Init Command
description: Initialize new midil-kit projects with scaffolding templates
---

# Init Command

The `init` command scaffolds new midil-kit projects using Cookiecutter templates, creating a complete project structure with configuration files and boilerplate code.

## Usage

```bash
midil init [NAME] [--type TYPE]
```

### Parameters

- `NAME` (optional): Project name *(default: midil-project)*
- `--type TYPE`: Project type *(choices: fastapi, lambda)* *(default: fastapi)*

## Examples

### Create FastAPI Service

```bash
# Create a new FastAPI service with default name
midil init

# Create a named FastAPI service
midil init my-api --type fastapi

# Create a service with custom name
midil init user-management-service
```

### Create Lambda Function

```bash
# Create a Lambda function project
midil init my-lambda --type lambda
```

## Project Structure

### FastAPI Projects

When you run `midil init my-api --type fastapi`, it creates:

```
services/
└── my-api/
    ├── main.py              # FastAPI application entry point
    ├── pyproject.toml       # Poetry configuration
    ├── poetry.toml          # Poetry lock file
    ├── README.md            # Project documentation
    └── Dockerfile           # Optional Docker support
```

### Generated Files

#### main.py
```python
from fastapi import FastAPI

app = FastAPI(title="My API", version="0.1.0")

@app.get("/")
async def root():
    return {"message": "Hello from My API"}
```

#### pyproject.toml
```toml
[tool.poetry]
name = "my-api"
version = "0.1.0"
description = "A project created with MIDIL CLI"
authors = ["Your Name <your.email@example.com>"]
```

## Command Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--type` | Choice | `fastapi` | Project type: `fastapi` or `lambda` |
| `NAME` | String | `midil-project` | Project name (slugified) |

## Template System

The init command uses Cookiecutter templates located in `cli/core/templates/`:

### Template Variables

The following variables are automatically generated:

- `project_name`: Human-readable project name
- `project_slug`: URL-safe project identifier
- `project_short_description`: Brief project description
- `author_name`: Your name *(inferred from git config)*
- `author_email`: Your email *(inferred from git config)*
- `service_version`: Initial version *(0.1.0)*
- `python_version`: Python version *(3.12)*
- `include_docker`: Docker support flag *(n)*

### Custom Templates

You can create custom templates by:

1. Creating a new directory in `cli/core/templates/`
2. Adding a `cookiecutter.json` configuration file
3. Implementing the template structure
4. Updating the scaffolder factory

## Troubleshooting

### Common Issues

1. **Permission Denied**
   ```bash
   # Ensure you have write permissions
   chmod 755 .
   ```

2. **Template Not Found**
   ```bash
   # Verify midil-kit installation
   pip show midil-kit
   ```

3. **Cookiecutter Error**
   ```bash
   # Install cookiecutter if missing
   pip install cookiecutter
   ```

### Debug Mode

Enable verbose output to debug scaffolding issues:

```bash
# Check what files will be created
midil init my-api --type fastapi --verbose
```

## Post-Generation Hooks

The init command includes post-generation hooks that:

- Remove Docker files if not requested
- Create additional directories (`tests/`)
- Generate `__init__.py` files for Python packages
- Apply project-specific customizations

## Integration with Development Workflow

### After Initialization

1. **Navigate to the project**:
   ```bash
   cd services/my-api
   ```

2. **Install dependencies**:
   ```bash
   poetry install
   ```

3. **Run the service**:
   ```bash
   midil launch --reload
   ```

4. **Run tests**:
   ```bash
   midil test --coverage
   ```

### Customization

After scaffolding, you can customize:

- **Dependencies**: Edit `pyproject.toml`
- **Application Logic**: Modify `main.py`
- **Configuration**: Add environment variables
- **Documentation**: Update `README.md`

## Advanced Usage

### Batch Project Creation

```bash
# Create multiple projects
for service in api-gateway user-service auth-service; do
    midil init $service --type fastapi
done
```

### Custom Project Names

```bash
# Use descriptive names (will be slugified)
midil init "User Management API" --type fastapi
# Creates: services/user-management-api/
```

<!-- source: midil-kit-main/midil/cli/commands/init.py -->
<!-- source: midil-kit-main/midil/cli/core/scaffolds/factory.py -->
<!-- source: midil-kit-main/midil/cli/core/scaffolds/fastapi.py -->
