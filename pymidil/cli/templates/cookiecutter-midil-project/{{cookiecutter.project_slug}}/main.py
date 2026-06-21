from fastapi import FastAPI

app = FastAPI(
    title="{{cookiecutter.project_name}}",
    description="{{cookiecutter.project_short_description}}",
    version="{{cookiecutter.service_version}}",
)


@app.get("/")
async def root():
    """Root endpoint returning a welcome message."""
    return {
        "message": "Hello from {{cookiecutter.project_name}}!",
        "version": "{{cookiecutter.service_version}}",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
