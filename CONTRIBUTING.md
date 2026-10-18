# Contributing to Yukti

Thank you for your interest in contributing to **Yukti — AI Teaching Assistant**!

We welcome contributions that improve AI-powered tutoring, adaptive learning, study-resource generation, reliability, accessibility, documentation, and the overall learning experience.

## Table of Contents

- Getting Started
- Types of Contributions
- Development Workflow
- Coding Guidelines
- Testing
- Pull Request Guidelines
- Reporting Bugs
- Suggesting Features
- Security Guidelines
- Code of Conduct

## Getting Started

Before contributing, make sure you have:

- Git installed.
- Python 3.11 available.
- Node.js and npm installed.
- Access to the required AI provider credentials and database services.
- Redis configured if you are working with background tasks.

Review the project's README for installation instructions and environment configuration.

## Types of Contributions

Contributions are welcome in areas such as:

- AI tutoring and RAG improvements.
- Learner mastery estimation and adaptive learning paths.
- Misconception detection and adaptive question selection.
- Quiz, flashcard, notes, and mind-map functionality.
- Frontend usability and accessibility.
- Backend APIs, database reliability, and error handling.
- Automated tests, bug fixes, and documentation.

## Development Workflow

### 1. Fork the Repository

Fork the Yukti repository to your GitHub account.

### 2. Clone Your Fork

```bash
git clone https://github.com/YOUR_USERNAME/Yukti.git
cd Yukti
```

Replace `YOUR_USERNAME` with your GitHub username.

### 3. Add the Original Repository as Upstream

```bash
git remote add upstream https://github.com/atharvahule24/Yukti.git
```

If an upstream remote already exists, verify it rather than adding it again.

### 4. Create a Branch

Create a descriptive branch for your changes.

```bash
git checkout -b feature/your-feature-name
```

For bug fixes:

```bash
git checkout -b fix/your-bug-name
```

### 5. Make Your Changes

- Keep changes focused on the issue or feature.
- Follow the existing project structure and conventions.
- Avoid unrelated refactoring.
- Update documentation when behavior or setup instructions change.
- Never commit secrets, generated credentials, or private user data.

### 6. Commit Your Changes

Use clear, descriptive commit messages.

```bash
git add <changed-files>
git commit -m "feat: improve adaptive learning recommendations"
```

Other examples:

```text
fix: handle quiz generation errors
docs: update installation instructions
test: add mastery engine test cases
refactor: simplify learner state updates
```

### 7. Push Your Branch

```bash
git push origin feature/your-feature-name
```

### 8. Open a Pull Request

Open a pull request against the original repository's default branch.

Include:

- A clear summary of the changes.
- The problem being addressed.
- Relevant testing performed.
- Screenshots for significant UI changes.
- Known limitations or follow-up work.

Address review feedback and keep the pull request focused.

## Coding Guidelines

### Python and Backend

- Use meaningful function and variable names.
- Keep functions focused and maintainable.
- Handle API failures and unexpected inputs appropriately.
- Avoid exposing secrets or sensitive information in logs.
- Preserve existing API contracts unless a change is necessary and documented.

### Frontend

- Follow the existing React and TypeScript conventions.
- Build reusable components where appropriate.
- Handle loading, error, and empty states.
- Keep the interface accessible and responsive.

### Adaptive Learning

- Make mastery and recommendation logic understandable and testable.
- Avoid treating a single incorrect answer as definitive proof of a misconception.
- Keep learner-state updates consistent with the evidence available.
- Document assumptions behind scoring thresholds and recommendation rules.
- Test edge cases involving missing data and repeated attempts.

## Testing

Run relevant tests before submitting a pull request.

For backend tests:

```bash
python -m pytest
```

For frontend lint checks and production builds, run these commands from the `frontend/` directory:

```bash
npm run lint
npm run build
```

If a change affects database persistence, background jobs, AI generation, or adaptive-learning workflows, test the affected functionality where practical.

Report any tests that could not be run and explain why.

## Reporting Bugs

When opening a bug report, include:

- A clear description of the issue.
- Steps to reproduce the problem.
- Expected and actual behavior.
- Relevant error messages or sanitized logs.
- Environment details when relevant.

Do not include API keys, passwords, access tokens, or private learner data.

## Suggesting Features

Before implementing a significant feature, open a GitHub issue to discuss the problem and proposed approach.

Explain:

1. The user problem being addressed.
2. The proposed solution.
3. How the feature benefits learners.
4. Potential implementation considerations.
5. Any limitations or dependencies.

This helps avoid duplicated work and unnecessary architectural changes.

## Security Guidelines

- Keep `.env` files and credentials out of version control.
- Use environment variables for sensitive configuration.
- Never include real learner records in tests or public examples.
- Report suspected vulnerabilities privately to the project maintainer.
- Avoid publishing exploit details before an issue has been addressed.

## Code of Conduct

All contributors are expected to follow the project's [Code of Conduct](CODE_OF_CONDUCT.md).

## Questions and Support

For questions, feature discussions, or bug reports, use the repository's GitHub Issues and other available project discussion channels.

Thank you for helping make Yukti a better learning platform!

