import streamlit as st
import os
import sys
from openai import OpenAI

# Add current directory to Python path if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from context import context  # ← Import your system prompt from context.py

# Configure Streamlit page
st.set_page_config(
    page_title="AwakenedEYE",
    layout="wide"
)

# Initialize chat history in session state
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Config from Streamlit secrets
OPENAI_API_KEY = st.secrets["openai_api_key"]
OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
ANSWER_MODEL = "google/gemini-2.5-flash-lite-preview-09-2025"

# App header
st.title("🧮 IQEd Math Chatbot")
st.markdown("---")

# Display chat history
chat_container = st.container()
with chat_container:
    for message in st.session_state.chat_history:
        if message["role"] == "user":
            st.chat_message("user").write(message["content"])
        else:
            st.chat_message("assistant").write(message["content"])

# Chat input box
query_input = st.chat_input("Enter your mathematical query...")

# Function to get chatbot response
def get_chatbot_response(query: str):
    try:
        # Initialize OpenAI client
        client = OpenAI(
            base_url=OPENAI_BASE_URL,
            api_key=OPENAI_API_KEY,
            
        )

        # Maintain only the last 8 messages
        conversation_history = st.session_state.chat_history[-8:] if len(st.session_state.chat_history) > 8 else st.session_state.chat_history

        # Build conversation context
        messages = [{"role": "system", "content": context}]
        for msg in conversation_history:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": query})

        # Generate completion
        with st.spinner("🤖 Thinking..."):
            completion = client.chat.completions.create(
                extra_body={},
                model=ANSWER_MODEL,
                messages=messages
            )
            answer = completion.choices[0].message.content

        return answer

    except Exception as e:
        st.error(f"❌ **Error:** {e}")
        return None

# Handle user input
if query_input:
    # Add user message to chat history
    st.session_state.chat_history.append({"role": "user", "content": query_input})

    # Get chatbot response
    answer = get_chatbot_response(query_input)

    if answer:
        # Add assistant reply to history
        st.session_state.chat_history.append({"role": "assistant", "content": answer})
        st.rerun()
    else:
        st.error("❌ Failed to get a response. Please try again.")
