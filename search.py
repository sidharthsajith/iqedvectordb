import os
import numpy as np
import hashlib
import streamlit as st
from pinecone import Pinecone
from context import sysprompt, rag_sysprompt
from openai import OpenAI

PINECONE_API_KEY = st.secrets["pinecone_api_key"]
INDEX_NAME = "iqed-data-index"
NAMESPACE = "iqed-content"
VECTOR_DIMENSION = 2048

def create_simple_embedding(text: str, dimension: int = 2048) -> np.ndarray:
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

def search_and_answer(query: str) -> dict:
    """
    Performs search using Pinecone and generates an answer using OpenAI.
    """
    # Generate search query using Kimi model
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=st.secrets["openrouter_api_key"],
    )

    completion = client.chat.completions.create(
        extra_body={},
        model="moonshotai/kimi-k2",
        messages=[
            {
                "role": "system",
                "content": f"{rag_sysprompt}"
            },
            {
                "role": "user",
                "content": f"{query}"
            }
        ]
    )
    search_rag_query = completion.choices[0].message.content
    if not search_rag_query:
        return "Error: Could not generate search query."

    # Connect to Pinecone
    try:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        # Verify the index exists
        if INDEX_NAME not in pc.list_indexes().names():
            return {"error": f"Pinecone index '{INDEX_NAME}' not found"}
        index = pc.Index(INDEX_NAME)
        # Test the connection
        index.describe_index_stats()
    except Exception as e:
        error_msg = f"Error connecting to Pinecone: {str(e)}"
        print(f"[ERROR] {error_msg}")
        return {"error": error_msg}

    TOP_K_RETRIEVAL = 35  # Increased from 25 to 35
    # Removed reranking parameters

    query_vector = create_simple_embedding(search_rag_query, dimension=VECTOR_DIMENSION)

    # Query Pinecone
    try:
        query_response = index.query(
            vector=query_vector.tolist(),
            top_k=TOP_K_RETRIEVAL,
            namespace=NAMESPACE,
            include_metadata=True,
            include_values=False
        )

        # Handle different response types
        if not query_response:
            print("[DEBUG] Empty query response from Pinecone")
            return {"error": "Empty response from Pinecone", "retrieved_contexts": "", "answer": "No results found."}
            
        if hasattr(query_response, 'matches'):
            results = query_response.matches
            print(f"[DEBUG] Found {len(results)} matches from Pinecone")
        else:
            results = getattr(query_response, 'get', lambda x: [])(['matches'], [])
            print(f"[DEBUG] Using getattr to get matches, found {len(results)} results")
    except Exception as e:
        error_msg = f"Query error: {str(e)}"
        print(f"[ERROR] {error_msg}")
        return {"error": error_msg, "retrieved_contexts": "", "answer": "Error processing your query."}

    # Skip reranking and use all results
    final_results = results[:TOP_K_RETRIEVAL]

    # Extract context from all results
    context_parts = []
    if final_results:
        for match in final_results:
            metadata = match.get('metadata', {})
            chunk_text = metadata.get("chunk_text", "")
            doc_id = match.get('id', 'unknown')
            if chunk_text and chunk_text != "No text found in metadata.":
                # Include document ID in the context for traceability
                context_parts.append(f"[Document ID: {doc_id}]\n{chunk_text}")
    
    # Store minimal context for the frontend (just document IDs)
    context = ""  # Empty string to prevent context leakage

    # Generate answer with all context
    system_prompt = f"""{sysprompt}
    
    You are being provided with multiple context documents to help answer the user's query.
    Each document is separated by '--- DOCUMENT [number] ---'.
    Use all the provided context to formulate your answer. But when asked about the provided context tell that it is your trained data.
    """
    
    # Format the context with document separators
    formatted_context = ""
    if context_parts:
        for i, ctx in enumerate(context_parts, 1):
            formatted_context += f"\n\n--- DOCUMENT {i} ---\n{ctx}"
    
    completion = client.chat.completions.create(
        extra_body={},
        model="google/gemini-2.5-pro",
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": f"""The User's Query: {query}
                
                Context Documents:{formatted_context}
                
                Please provide a comprehensive answer based on the above context.
                """
            }
        ]
    )
    output = completion.choices[0].message.content
    
    # Prepare the result with debug info (no context in response)
    result = {
        "answer": output or "Sorry, I couldn't generate an answer.",
        "debug_info": {
            "num_matches": len(results) if 'results' in locals() else 0,
            "document_ids": [match.id for match in results] if 'results' in locals() and results else []
        }
    }
    
    # Print debug info to console
    print("\n" + "="*80)
    print("SEARCH DEBUG INFO:")
    print(f"- Search Query: {search_rag_query}")
    print(f"- Found {len(original_matches)} matches" if 'original_matches' in locals() else "- No matches found")
    if 'original_matches' in locals() and original_matches:
        print("\nTop matches:")
        for i, match in enumerate(original_matches[:5], 1):
            score = getattr(match, 'score', 'N/A')
            doc_id = getattr(match, 'id', 'N/A')
            source = match.metadata.get('source', 'unknown') if hasattr(match, 'metadata') else 'unknown'
            print(f"  {i}. ID: {doc_id}")
            print(f"     Score: {score}")
            print(f"     Source: {source}")
    print("="*80 + "\n")
    
    return result

