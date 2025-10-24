import os
import numpy as np
import hashlib
import streamlit as st
from pinecone import Pinecone
from context import context, sysprompt

actualquery = """
∫  1/ ( x + 10)  (x + 15)   dx
∫  1/ ( x + 8 )  (x + 4)   dx
∫  1/ ( x + 3 )  (x + 9)   dx
∫  1/ ( x + 2 )  (x + 5 )   dx
∫  1/ ( x + 9 )  (x + 6 )   dx
"""


from openai import OpenAI

client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key=st.secrets["openai_api_key"],
)

completion = client.chat.completions.create(
  extra_body={},
  model="moonshotai/kimi-k2",
  messages=[
          {
      "role": "system",
      "content": f"{context}"
    },
    {
      "role": "user",
      "content": f"{actualquery}"
    }
  ]
)
search_rag_query =completion.choices[0].message.content 


PINECONE_API_KEY = st.secrets["pinecone_api_key"]
INDEX_NAME = "iqed-data-index"
NAMESPACE = "iqed-content"
VECTOR_DIMENSION = 128


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


try:

    pc = Pinecone(api_key=PINECONE_API_KEY)
    

    index = pc.Index(name=INDEX_NAME)

    print(f"Successfully connected to index: {INDEX_NAME}")

except Exception as e:
    print(f"Error connecting to Pinecone: {e}")
    exit()


TOP_K_RETRIEVAL = 25 
TOP_N_RERANK = 10

RERANKER_MODEL = "bge-reranker-v2-m3" 

query_vector = create_simple_embedding(actualquery, dimension=VECTOR_DIMENSION)




query_results = index.query(
    vector=query_vector.tolist(),  
    top_k=TOP_K_RETRIEVAL, 
    namespace=NAMESPACE,
    include_metadata=True,        
    include_values=False          
)


documents_to_rerank = [
    match.metadata.get("chunk_text", "No text found in metadata.")
    for match in query_results.matches
]
original_matches = query_results.matches


if not documents_to_rerank:
    final_results = []
else:

    
    try:

        rerank_results = pc.inference.rerank(
            model=RERANKER_MODEL,
            query=actualquery,
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



if not final_results:
    print("No final results to display.")
else:
    for match in final_results:
        chunk_text = match.metadata.get("chunk_text", "No text found in metadata.")
        filename = match.metadata.get("filename", "N/A")
        

context = chunk_text

client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key=st.secrets["openai_api_key"],
)

completion = client.chat.completions.create(
  extra_body={},
  model="google/gemini-2.5-pro",
  messages=[
          {
      "role": "system",
      "content": f"{sysprompt}"
    },
    {
      "role": "user",
      "content": f"The Query from the User: {actualquery} \n \n The Context from the Document: {context}"
    }
  ]
)
output = completion.choices[0].message.content 

print(output)

