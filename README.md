# Yukti — AI Teaching Assistant

An AI-powered learning platform designed to help students understand concepts, practice questions, and create personalized study materials through intelligent tutoring.

## Overview

Yukti is an AI Teaching Assistant that supports interactive learning through AI-powered conversations and automated study-resource generation. It aims to make learning more accessible, structured, and engaging for students.

## Features

- **AI-Powered Tutoring:** Get explanations and assistance with academic concepts.
- **RAG-Based Chat:** Ask questions grounded in uploaded learning materials.
- **Quiz Generation:** Generate quizzes to test your understanding.
- **Flashcards:** Create flashcards for revision and active recall.
- **Notes Generation:** Turn learning content into structured study notes.
- **Mind Maps:** Organize concepts visually to understand their relationships.
- **Document Uploads:** Upload learning materials for AI-assisted study.
- **Persistent Storage:** Save supported learning resources and session data.

## Tech Stack

| Component | Technology |
|---|---|
| Frontend | React |
| Backend | Python |
| AI / LLM | Groq API |
| Retrieval-Augmented Generation | RAG |
| Vector Search | FAISS |
| Database | Supabase |
| Background Processing | Celery and Redis |

*Note: Update this table if your current implementation uses different technologies for any component.*

## Architecture

```text
                  Student
                     |
                     v
              React Frontend
                     |
                     v
                Backend API
                     |
          +----------+----------+
          |          |          |
          v          v          v
       AI Chat     Quiz      Study Tools
          |          |          |
          +----------+----------+
                     |
                     v
              RAG / AI Services
                     |
          +----------+----------+
          |                     |
          v                     v
       FAISS                Groq API
          |
          v
   Relevant Learning Context

          Persistent Data
                 |
                 v
              Supabase
```

## Getting Started

### Prerequisites

Before running the project locally, ensure you have the following installed:

- Python
- Node.js and npm
- Git
- Access to the required AI API and database services

### 1. Clone the Repository

```bash
git clone https://github.com/atharvahule24/Yukti.git
cd Yukti
```

### 2. Configure Environment Variables

Check the backend and frontend directories for their respective `.env.example` files.

Create local `.env` files based on those examples and configure the required credentials.

Typical configuration may include:

- Groq API key
- Supabase URL and credentials
- Redis connection URL
- Backend API URL for the frontend

Use the exact variable names defined by the project. Never commit real API keys or secrets.

### 3. Install Backend Dependencies

Navigate to the backend directory and install the dependencies using the project's dependency file.

```bash
pip install -r requirements.txt
```

### 4. Install Frontend Dependencies

Navigate to the frontend directory and run:

```bash
npm install
```

### 5. Run the Application

Start the backend and frontend using the commands and configuration specified in their respective project directories.

If background jobs are enabled, configure and start the required Redis and Celery services as documented in the project.

## Usage

1. Open the application.
2. Upload relevant learning material, where supported.
3. Ask questions through the AI chat interface.
4. Generate quizzes, flashcards, notes, or mind maps.
5. Use the generated resources to revise and assess your understanding.

## Project Structure

```text
Yukti/
├── frontend/          # React application
├── backend/           # Backend APIs and AI services
├── README.md          # Project documentation
├── CODE_OF_CONDUCT.md # Community standards
└── CONTRIBUTING.md    # Contribution guidelines
```

*The directory names above are illustrative. Adjust them to match the actual repository structure.*

## Contributing

Contributions, suggestions, and bug reports are welcome.

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a pull request and follow the guidelines in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Security

- Do not commit API keys, passwords, or private credentials.
- Report security vulnerabilities responsibly.
- Avoid uploading sensitive personal or academic information.

## License

Specify the project's license here. If no license has been selected, review the available open-source licenses before adding one.

## Author

**Atharva Hule**

GitHub: [@atharvahule24](https://github.com/atharvahule24)

---

If you find this project useful, consider giving the repository a star!

