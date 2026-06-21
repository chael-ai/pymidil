# Contribution

## Changelog Management - Overview

The changelog system automatically generates changelog entries from git commits that follow the [Conventional Commits](https://www.conventionalcommits.org/) specification. This ensures consistent, readable changelogs and enables automated release management.

## Setup

### 1. Git Commit Template

The project includes a `.gitmessage` template that provides guidance for writing conventional commits. To activate it:

```bash
git config commit.template .gitmessage
```

Now when you run `git commit` (without `-m`), your editor will open with the template.

### 2. Changelog Script

The `scripts/changelog.py` script handles all changelog operations. It's already configured in the Makefile for easy use.

## Usage

### Preview Changes

Before updating the changelog, you can preview what changes will be made:

```bash
make changelog-preview
```

This shows what the new changelog entries would look like without modifying the file.

### Update Changelog

To update the changelog with new commits since the last release:

```bash
make changelog
```

This will:
1. Read all commits since the last git tag
2. Parse conventional commit messages
3. Categorize changes by type
4. Update the `[Unreleased]` section in `CHANGELOG.md`

### Create a Release

When you're ready to create a new release:

```bash
make create-release
```

This will prompt you for a version number and:
1. Update the changelog
2. Replace `[Unreleased]` with the new version
3. Add the release date
4. Add version comparison links

### Bump Version and Release

To bump the version and prepare a release in one step:

```bash
make release
```

This will:
1. Prompt for release type (patch/minor/major)
2. Bump the version in `pyproject.toml`
3. Update the changelog
4. Prepare the release

## Commit Message Format

### Basic Format

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Types

- `feat`: A new feature
- `fix`: A bug fix
- `docs`: Documentation only changes
- `style`: Changes that do not affect the meaning of the code
- `refactor`: A code change that neither fixes a bug nor adds a feature
- `test`: Adding missing tests or correcting existing tests
- `chore`: Changes to the build process or auxiliary tools
- `perf`: A code change that improves performance
- `ci`: Changes to CI configuration files and scripts
- `build`: Changes that affect the build system or external dependencies
- `revert`: Reverts a previous commit

### Scopes

- `jsonapi`: JSON:API core functionality
- `docs`: Documentation
- `ci`: Continuous integration
- `deps`: Dependencies

### Examples

**Feature:**
```
feat(jsonapi): add support for sparse fieldsets

This allows clients to request only specific fields from resources,
reducing payload size and improving performance.
```

**Bug Fix:**
```
fix(jsonapi): resolve validation error in relationship serialization

The serializer was not properly handling nested relationship objects.
This fix ensures all relationship data is correctly serialized.

Fixes #123
```

**Breaking Change:**
```
feat(jsonapi): remove deprecated ResourceObject constructor

BREAKING CHANGE: The ResourceObject constructor signature has changed.
The `type` parameter is now required and must be provided as the first
argument.

Migration guide:
- Old: ResourceObject(id="1", type="articles", ...)
- New: ResourceObject("articles", id="1", ...)
```

## Changelog Structure

The generated changelog follows the [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
# Changelog

## [Unreleased]

### Breaking Changes
- **BREAKING:** remove deprecated ResourceObject constructor (jsonapi)

### Added
- add support for sparse fieldsets (jsonapi)
- add comprehensive error handling (jsonapi)

### Fixed
- resolve validation error in relationship serialization (jsonapi)

### Documentation
- update README with usage examples (docs)

## [0.1.0] - 2024-01-01

### Added
- Initial release
- Basic JSON:API document creation and validation
- Error handling utilities
- Type-safe Pydantic models

```

## Manual Usage

You can also use the changelog script directly:

```bash
# Update changelog since a specific tag
python scripts/changelog.py update --since v0.1.0

# Preview changes since a specific commit
python scripts/changelog.py preview --since abc1234

# Create a release with a specific version
python scripts/changelog.py release --version 0.2.0
```

## Best Practices

1. **Write clear commit messages**: Use descriptive, present-tense messages
2. **Use appropriate types**: Choose the right type for your changes
3. **Include scope when relevant**: Helps categorize changes
4. **Document breaking changes**: Always include migration information
5. **Keep commits focused**: One logical change per commit
6. **Update changelog regularly**: Don't let it get out of sync

## Troubleshooting

### No conventional commits found

If you see "No conventional commits found", it means your commits don't follow the conventional format. Update your commit messages or use the template.

### Script errors

Make sure you're in a git repository and have the necessary permissions to read git history.

### Version conflicts

If you get version conflicts, make sure you're using semantic versioning and that the version number is higher than the previous release.
