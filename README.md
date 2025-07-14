# AI Conversation Assistant

An AI-powered desktop assistant that listens to your video calls, captures speech in real time, and sends it to a Large Language Model (LLM) for contextual suggestions. The assistant then prints a reply that you can read and use as your own during meetings or calls.

## ✨ Features

- 🎙️ Real-time voice capture from video calls (e.g., Zoom, Meet, Skype)
- 🔊 Voice Activity Detection (VAD) for auto-triggered recording
- 🧠 Google Gemini integration (chat-based only)
- 📸 Optional screenshot bundling for multimodal context
- 🖥️ Overlay GUI with hotkeys, history, and customizable display
- ⚙️ Dynamic config via `config.yaml` — no restart required

## 🧠 Use Case

Perfect for:
- Job interviews
- Business meetings
- Virtual classrooms
- Live sales calls or consultations

The app helps you keep up, think faster, and communicate confidently.

---

## 🚀 How to Install & Run (Windows Only)

> 💡 Requires Python **3.13** installed and added to PATH.

1. Download or clone this repository.
2. Double-click `install.bat`  
   This will:
   - Create a virtual environment
   - Install all required dependencies
3. Once setup is complete, double-click `launch.bat`
   This will start the assistant.
   
   **Important:** For the app to behave according to your needs, configure `config/config.yaml` and `config/system_prompt.txt` before launching.

---

## 🔧 Configuration

Customize the app using `config.yaml`:

- LLM behavior and reply format
- Screenshot capture settings
- GUI appearance and hotkeys
- Auto-VAD and manual recording options

---

## 🧪 About Development

The app was developed with the assistance of **Kilocode**, leveraging the free tier of **Gemini Flash 2.5 (Thinking)**, with additional support from the free tier of **ChatGPT** during the development process.

---

## 📜 License

This project is licensed under the MIT License. See [LICENSE](./LICENSE).

Includes dependencies licensed under:
- Apache 2.0 (Google Generative AI SDKs)
- MIT, BSD, PSF, and MPL (e.g. tqdm)

See [NOTICE](./NOTICE) for full third-party attribution.
