import streamlit as st
import os
import numpy as np
import hashlib
from pinecone import Pinecone
from openai import OpenAI
import sys

# Add current directory to Python path to import from other files
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from context import context, sysprompt

# Configure Streamlit page
st.set_page_config(
    page_title="AwakenedEYE",
    layout="wide"
)

# Initialize chat history in session state
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Configuration from Streamlit secrets
PINECONE_API_KEY = st.secrets["pinecone_api_key"]
INDEX_NAME = "iqed-data-index"
NAMESPACE = "iqed-content"
VECTOR_DIMENSION = 128
OPENAI_API_KEY = st.secrets["openai_api_key"]
OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
search_model = "moonshotai/kimi-k2"
answer_model = "google/gemini-2.5-pro"
TOP_K_RETRIEVAL = 25
TOP_N_RERANK = 10
RERANKER_MODEL = "bge-reranker-v2-m3"

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

# Chat input
query_input = st.chat_input("Enter your mathematical query...")

# Function to create simple embedding
def create_simple_embedding(text: str, dimension: int = 128) -> np.ndarray:
    hash_object = hashlib.md5(text.encode())
    hex_dig = hash_object.hexdigest()
    
    embedding = []
    for i in range(0, min(len(hex_dig), dimension * 2), 2):
        hex_pair = hex_dig[i:i+2]
        val = int(hex_pair, 16) / 255.0 - 0.5
        embedding.append(val)
    
    while len(embedding) < dimension:
        embedding.append(0.0)
    
    return np.array(embedding[:dimension])

# Function to perform search
def perform_search(query):
    try:
        # Initialize OpenAI client
        client = OpenAI(
            base_url=OPENAI_BASE_URL,
            api_key=OPENAI_API_KEY,
        )
        
        # Generate search query using context
        with st.spinner("🔄 Generating optimized search query..."):
            completion = client.chat.completions.create(
                extra_body={},
                model=search_model,
                messages=[
                    {
                        "role": "system",
                        "content": f"{context}"
                    },
                    {
                        "role": "user",
                        "content": f"{query}"
                    }
                ]
            )
            search_rag_query = completion.choices[0].message.content
        
        # Initialize Pinecone
        pc = Pinecone(api_key=PINECONE_API_KEY)
        index = pc.Index(name=INDEX_NAME)
        
        # Create embedding and search
        with st.spinner("🔍 Searching vector database..."):
            query_vector = create_simple_embedding(query, dimension=VECTOR_DIMENSION)
            
            query_results = index.query(
                vector=query_vector.tolist(),
                top_k=TOP_K_RETRIEVAL,
                namespace=NAMESPACE,
                include_metadata=True,
                include_values=False
            )
        
        # Reranking
        documents_to_rerank = [
            match.metadata.get("chunk_text", "No text found in metadata.")
            for match in query_results.matches
        ]
        original_matches = query_results.matches
        
        if not documents_to_rerank:
            final_results = []
        else:
            with st.spinner("🔄 Reranking results..."):
                try:
                    rerank_results = pc.inference.rerank(
                        model=RERANKER_MODEL,
                        query=query,
                        documents=documents_to_rerank,
                        top_n=TOP_N_RERANK,
                        return_documents=False
                    )
                    
                    final_results = []
                    for rerank_match in rerank_results.data:
                        original_index = rerank_match.index
                        original_pinecone_match = original_matches[original_index]
                        original_pinecone_match.score = rerank_match.score
                        final_results.append(original_pinecone_match)
                
                except Exception as e:
                    final_results = original_matches[:TOP_N_RERANK]
        
        # Generate final answer with conversation history
        if final_results:
            best_match = final_results[0]
            context_text = best_match.metadata.get("chunk_text", "No text found in metadata.")
            
            # Prepare conversation history (last 8 messages)
            conversation_history = st.session_state.chat_history[-8:] if len(st.session_state.chat_history) > 8 else st.session_state.chat_history
            
            # Build messages for Gemini
            messages = [{"role": "system", "content": f"{sysprompt}"}]
            
            # Add conversation history
            for msg in conversation_history:
                messages.append({"role": msg["role"], "content": msg["content"]})
            
            # Add current query with context
            messages.append({
                "role": "user", 
                "content": f"The Query from the User: {query} \n \n The Context from the Document: {context_text}"
            })
            
            with st.spinner("🤖 Generating answer..."):
                completion = client.chat.completions.create(
                    extra_body={},
                    model=answer_model,
                    messages=messages
                )
                answer = completion.choices[0].message.content
            
            return {
                "search_query": search_rag_query,
                "context": context_text,
                "answer": answer,
                "all_results": final_results,
                "metadata": best_match.metadata
            }
        else:
            return None
    
    except Exception as e:
        st.error(f"❌ **Error during search:** {e}")
        return None

# Handle user input
if query_input:
    # Add user message to chat history
    st.session_state.chat_history.append({"role": "user", "content": query_input})
    
    # Perform search and get response
    with st.spinner("🤔 Thinking..."):
        result = perform_search(query_input)
        
        if result:
            # Add assistant response to chat history
            st.session_state.chat_history.append({"role": "assistant", "content": result["answer"]})
            
            # Rerun to update the chat display
            st.rerun()
        else:
            st.error("❌ Failed to get a response. Please try again.")