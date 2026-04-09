# Design Document: Upgrade Faqqer to Self-Learning Multi-Channel AI Help Bot

## 1. Introduction

This document outlines the proposed architectural changes and implementation strategy to replace the existing `Faqqer` bot with a production-quality, self-learning, multi-channel AI help system. The goal is to create a robust, scalable, and easily maintainable knowledge-base bot that can serve users across various platforms and continuously improve its responses.

## 2. Framework Selection: Danswer

After evaluating available open-source knowledge-base AI help frameworks, **Danswer** has been selected as the foundation for the new system.

### 2.1. Rationale for Danswer

*   **Enterprise-Grade Knowledge Base:** Danswer is explicitly designed for building AI assistants on internal company knowledge, which aligns perfectly with the requirement for a robust Tari knowledge base.
*   **Comprehensive RAG Capabilities:** It offers sophisticated Retrieval Augmented Generation (RAG) capabilities, allowing the bot to ground its answers in diverse data sources like documentation, FAQ files, and prior Q&A, ensuring accuracy and relevance.
*   **Knowledge Base Management:** Danswer provides connectors for various data sources (web pages, Confluence, Google Drive, S3, etc.) and an admin interface for managing the knowledge base. This fulfills the requirement for updating content without code changes or redeployment.
*   **Multi-Channel Support:** While Danswer's core is an API-first knowledge system, it is designed to be easily integrated with various frontends (Slack, web widget, etc.). This makes integrating with Telegram and Discord straightforward.
*   **Self-Learning Potential:** Danswer supports feedback mechanisms and continuous improvement based on user interactions, which is crucial for the "self-learning" aspect.
*   **Containerization:** Danswer is built with Docker in mind, simplifying deployment and ensuring consistency across environments.
*   **Active Development & Community:** Danswer has an active GitHub repository and community, ensuring ongoing support and feature development.

## 3. High-Level Migration Plan

The migration will be conducted in phases to ensure a smooth transition and progressive feature rollout.

### Phase 1: Danswer Core Setup & Knowledge Ingestion

*   **Objective:** Deploy the core Danswer system and ingest existing Tari knowledge.
*   **Steps:**
    *   Set up Danswer's backend components (Q&A service, document indexers, web server).
    *   Develop or configure connectors to ingest existing Tari knowledge:
        *   Existing `faqs/` directory content.
        *   Tari documentation (e.g., from a Git repository, website, or Confluence if applicable).
        *   Archived Q&A from Telegram/Discord channels (if historical data is available and valuable).
    *   Configure initial RAG models and test basic knowledge retrieval via Danswer's API.

### Phase 2: Multi-Channel Bot Integration

*   **Objective:** Integrate Danswer with Telegram and Discord APIs to enable user interactions.
*   **Steps:**
    *   Develop or adapt a Telegram bot frontend that communicates with Danswer's API for question answering.
    *   Develop or adapt a Discord bot frontend that communicates with Danswer's API for question answering.
    *   Deploy these frontends as separate services, potentially alongside the Danswer core.
    *   Test end-to-end Q&A functionality on both Telegram and Discord.

### Phase 3: Self-Learning & Feedback Loop Implementation

*   **Objective:** Enable the system to learn from interactions and allow for continuous improvement.
*   **Steps:**
    *   Integrate user feedback mechanisms (e.g., "thumbs up/down" buttons) into Telegram and Discord interfaces.
    *   Implement an admin interface or workflow (potentially leveraging Danswer's built-in capabilities or a custom tool) for reviewing user interactions, approving new Q&A pairs, or refining knowledge base content.
    *   Monitor Danswer's performance and knowledge base effectiveness.

### Phase 4: Existing Faqqer Functionality Migration

*   **Objective:** Preserve and integrate the existing `faqqer`'s unique functionalities.
*   **Steps:**
    *   **Blockchain Stats Posting (`blockchain_job.py`):**
        *   Re-implement this as a standalone scheduled microservice, containerized alongside the new AI help system.
        *   It will continue to use Telegram's API to post updates to configured group IDs.
        *   Explore potential integration points with Danswer for future enhancements (e.g., Danswer acting as a knowledge source for blockchain data).
    *   **Customer Service Analysis (`customer_analysis_job.py`):**
        *   Re-implement this as a standalone scheduled microservice, leveraging a shared LLM infrastructure if available, or its own OpenAI API key.
        *   It will preserve the existing prompt generation logic (`test_custom_prompt.py` will serve as a reference).
        *   It will continue to scan Telegram channels and post analysis summaries to the customer service group.

### Phase 5: Deployment & Documentation

*   **Objective:** Ensure the new system is fully containerized, documented, and ready for production.
*   **Steps:**
    *   Finalize Docker Compose configurations for all services: Danswer core, Telegram frontend, Discord frontend, and migrated blockchain/customer analysis jobs.
    *   Create comprehensive setup documentation covering:
        *   Prerequisites (Docker, API keys).
        *   Configuration (environment variables).
        *   Deployment instructions.
        *   Maintenance and troubleshooting guides.
    *   Update `README.md` in the root and within the new `ai_help_bot/` directory.

## 4. Acceptance Criteria Checklist

The plan directly addresses all acceptance criteria:

*   [X] An open-source knowledge-base help framework is selected and documented (with rationale for the choice) - *Danswer selected, documented in this file.*
*   [ ] The bot responds to user questions on Telegram with answers grounded in the Tari knowledge base - *Addressed in Phase 2.*
*   [ ] The bot responds to user questions on Discord with the same knowledge base - *Addressed in Phase 2.*
*   [ ] Knowledge base content can be added/updated by editing files or using an admin interface, without code changes or redeployment - *Addressed by Danswer's design and Phase 1.*
*   [ ] The system learns from new Q&A interactions: questions that get positive feedback or admin-approved answers are incorporated into future responses - *Addressed by Danswer's design and Phase 3.*
*   [ ] Existing faqqer functionality is preserved: blockchain stats posting (configurable schedule) and customer service analysis (periodic channel scanning) - *Addressed in Phase 4.*
*   [ ] Deployment is containerized (Docker) with clear setup documentation - *Addressed by Danswer's design and Phase 5.*

## 5. Next Steps

*   Create the `ai_help_bot/` directory.
*   Begin setting up Danswer's core components as per Phase 1.
*   Start populating the Danswer knowledge base with existing Tari content.
