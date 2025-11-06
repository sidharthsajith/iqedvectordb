import streamlit as st
import json
import numpy as np
from typing import List, Dict, Any, Optional, Tuple, cast
import hashlib
import re
from pinecone import Pinecone
from openai import OpenAI
from context import sysprompt, rag_sysprompt
from search import search_and_answer

# --- Client Initialization ---
try:
    # Initialize OpenRouter Client
    openrouter_client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=st.secrets["openrouter_api_key"],
    )
    
    # Initialize Pinecone
    pc = Pinecone(api_key=st.secrets["pinecone_api_key"])
    index_name = "iqed-data-index"
    if index_name not in pc.list_indexes().names():
        st.error(f"Pinecone index '{index_name}' does not exist.")
        st.stop()

except Exception as e:
    st.error(f"An error occurred during client initialization: {e}")
    st.stop()



# --- Streamlit App ---
st.set_page_config(page_title="IQEd Chat Search", layout="wide")
st.title("📚 IQEd - Chat Search with AwakenedEYE")

if 'logs' not in st.session_state:
    st.session_state.logs = []

if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

# Display chat history
for message in st.session_state.chat_history:
    with st.chat_message(message['role']):
        st.markdown(message['content'])

# Chat input
if prompt := st.chat_input("Ask a question about math, vedic math, or exam preparation."):
    # Add user message to history
    st.session_state.chat_history.append({'role': 'user', 'content': prompt})
    with st.chat_message('user'):
        st.markdown(prompt)

    # Perform search and generate answer
    st.session_state.logs = [f"User Query: {prompt}"]
    
    with st.spinner("Searching for relevant information..."):
        search_results = search_and_answer(prompt)
    
    # Handle the response
    final_answer = "Sorry, I encountered an error processing your request."
    
    if isinstance(search_results, dict):
        if "error" in search_results:
            error_msg = search_results['error']
            st.error(f"Error: {error_msg}")
            print(f"[ERROR] {error_msg}")
        elif "answer" in search_results:
            final_answer = search_results["answer"]
        else:
            error_msg = f"Unexpected response format from search_and_answer: {search_results}"
            st.error("An unexpected error occurred. Please try again.")
            print(f"[ERROR] {error_msg}")
    else:
        error_msg = f"Expected dictionary response, got {type(search_results).__name__}"
        st.error("An unexpected error occurred. Please try again.")
        print(f"[ERROR] {error_msg}")

    # Add assistant response to history
    st.session_state.chat_history.append({'role': 'assistant', 'content': final_answer})
    with st.chat_message('assistant'):
        st.markdown(final_answer)
        
        # Show document IDs in debug section
        if isinstance(search_results, dict) and 'debug_info' in search_results and 'document_ids' in search_results['debug_info']:
            with st.expander("🔍 View Document References", expanded=False):
                doc_ids = search_results['debug_info']['document_ids']
                if doc_ids:
                    st.write(f"📄 Referenced {len(doc_ids)} documents:")
                    cols = st.columns(5)  # 5 columns for document IDs
                    for i, doc_id in enumerate(doc_ids[:10]):  # Show first 10 IDs
                        with cols[i % 5]:
                            st.code(doc_id, language='text')
                    if len(doc_ids) > 10:
                        st.caption(f"+ {len(doc_ids) - 10} more documents...")

    # Limit to last 8 chats (16 messages: 8 user + 8 assistant)
    if len(st.session_state.chat_history) > 16:
        st.session_state.chat_history = st.session_state.chat_history[-16:]

# --- Debugging Section ---
with st.expander("Show Debug Information"):
    st.subheader("Execution Logs")
    for log in st.session_state.logs:
        st.text(log)
