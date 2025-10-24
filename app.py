import os
import re
from pathlib import Path
from typing import List, Dict, Any
import tiktoken
import numpy as np
import hashlib
import streamlit as st
from pinecone import Pinecone, ServerlessSpec

# Initialize Pinecone
pc = Pinecone(api_key=st.secrets["pinecone_api_key"])

index_name = "iqed-data-index"

# Delete existing index if it exists to recreate with proper configuration
if pc.has_index(index_name):
    print(f"Deleting existing index '{index_name}' to recreate with proper configuration...")
    pc.delete_index(index_name)
    print("Waiting for index deletion...")
    import time
    time.sleep(5)

# Create a standard index with smaller dimension for demo
print(f"Creating new index '{index_name}'...")
pc.create_index(
    name=index_name,
    dimension=128,  # Smaller dimension for simple hash-based embeddings
    metric="cosine",
    spec=ServerlessSpec(
        cloud="aws",
        region="us-east-1"
    )
)

# Wait for index to be ready
print("Waiting for index to be ready...")
import time
while not pc.describe_index(index_name).status['ready']:
    time.sleep(1)

# Initialize index client
index = pc.Index(name=index_name)

# Simple embedding function using hash-based approach
def create_simple_embedding(text: str, dimension: int = 128) -> np.ndarray:
    """Create a simple embedding using hash-based approach."""
    # Create a deterministic hash-based embedding
    hash_object = hashlib.md5(text.encode())
    hex_dig = hash_object.hexdigest()
    
    # Convert hex to numeric values
    embedding = []
    for i in range(0, min(len(hex_dig), dimension * 2), 2):
        hex_pair = hex_dig[i:i+2]
        val = int(hex_pair, 16) / 255.0 - 0.5  # Normalize to [-0.5, 0.5]
        embedding.append(val)
    
    # Pad or truncate to desired dimension
    while len(embedding) < dimension:
        embedding.append(0.0)
    
    return np.array(embedding[:dimension])

# View index stats
print(f"Index stats: {index.describe_index_stats()}")

class DataVectoriser:
    def __init__(self, data_dir: str = "data", chunk_size: int = 1000, chunk_overlap: int = 200):
        self.data_dir = Path(data_dir)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.encoding = tiktoken.get_encoding("cl100k_base")  # Using OpenAI's tokenizer
        
    def read_file(self, file_path: Path) -> str:
        """Read content from different file types."""
        try:
            if file_path.suffix.lower() == '.md':
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            elif file_path.suffix.lower() == '.txt':
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            elif file_path.suffix.lower() == '.pdf':
                # For PDF files, you might need additional processing
                print(f"PDF processing not implemented for {file_path}")
                return ""
            elif file_path.suffix.lower() in ['.docx', '.doc']:
                # For Word documents, you might need additional processing
                print(f"Word document processing not implemented for {file_path}")
                return ""
            else:
                print(f"Unsupported file type: {file_path.suffix}")
                return ""
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
            return ""
    
    def clean_text(self, text: str) -> str:
        """Clean and normalize text."""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove special characters but keep important ones
        text = re.sub(r'[^\w\s\.\,\!\?\;\:\-\(\)\[\]\{\}\"\'\/\\]', '', text)
        # Remove extra spaces around punctuation
        text = re.sub(r'\s+([.,!?;:])', r'\1', text)
        return text.strip()
    
    def chunk_text(self, text: str, metadata: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Split text into chunks using token-based approach."""
        if metadata is None:
            metadata = {}
            
        # Clean the text first
        text = self.clean_text(text)
        
        # Split into paragraphs first
        paragraphs = text.split('\n')
        paragraphs = [p.strip() for p in paragraphs if p.strip()]
        
        chunks = []
        current_chunk = ""
        current_tokens = 0
        
        for paragraph in paragraphs:
            paragraph_tokens = len(self.encoding.encode(paragraph))
            
            # If paragraph alone is too large, split it
            if paragraph_tokens > self.chunk_size:
                # Save current chunk if it exists
                if current_chunk:
                    chunks.append({
                        "text": current_chunk.strip(),
                        "metadata": {
                            **metadata,
                            "chunk_index": len(chunks),
                            "token_count": current_tokens
                        }
                    })
                    current_chunk = ""
                    current_tokens = 0
                
                # Split large paragraph into sentences
                sentences = re.split(r'[.!?]+', paragraph)
                sentences = [s.strip() for s in sentences if s.strip()]
                
                for sentence in sentences:
                    sentence_tokens = len(self.encoding.encode(sentence))
                    
                    if current_tokens + sentence_tokens > self.chunk_size:
                        if current_chunk:
                            chunks.append({
                                "text": current_chunk.strip(),
                                "metadata": {
                                    **metadata,
                                    "chunk_index": len(chunks),
                                    "token_count": current_tokens
                                }
                            })
                        current_chunk = sentence
                        current_tokens = sentence_tokens
                    else:
                        current_chunk += " " + sentence if current_chunk else sentence
                        current_tokens += sentence_tokens
            else:
                # Check if adding this paragraph exceeds chunk size
                if current_tokens + paragraph_tokens > self.chunk_size:
                    # Save current chunk
                    if current_chunk:
                        chunks.append({
                            "text": current_chunk.strip(),
                            "metadata": {
                                **metadata,
                                "chunk_index": len(chunks),
                                "token_count": current_tokens
                            }
                        })
                    
                    # Start new chunk with overlap
                    if self.chunk_overlap > 0 and chunks:
                        # Get overlap from previous chunk
                        prev_chunk = chunks[-1]["text"]
                        prev_tokens = self.encoding.encode(prev_chunk)
                        overlap_tokens = prev_tokens[-self.chunk_overlap:] if len(prev_tokens) > self.chunk_overlap else prev_tokens
                        overlap_text = self.encoding.decode(overlap_tokens)
                        current_chunk = overlap_text + " " + paragraph
                        current_tokens = len(self.encoding.encode(current_chunk))
                    else:
                        current_chunk = paragraph
                        current_tokens = paragraph_tokens
                else:
                    current_chunk += "\n" + paragraph if current_chunk else paragraph
                    current_tokens += paragraph_tokens
        
        # Save the last chunk
        if current_chunk:
            chunks.append({
                "text": current_chunk.strip(),
                "metadata": {
                    **metadata,
                    "chunk_index": len(chunks),
                    "token_count": current_tokens
                }
            })
        
        return chunks
    
    def extract_metadata(self, file_path: Path) -> Dict[str, Any]:
        """Extract metadata from file path and content."""
        metadata = {
            "filename": file_path.name,
            "file_path": str(file_path),
            "file_type": file_path.suffix.lower(),
            "file_size": file_path.stat().st_size if file_path.exists() else 0
        }
        
        # Extract level from filename if it's a LEVEL file
        if "LEVEL" in file_path.name:
            level_match = re.search(r'LEVEL (\d+)', file_path.name)
            if level_match:
                metadata["level"] = int(level_match.group(1))
        
        # Extract topic information from content
        content = self.read_file(file_path)
        if content:
            # Look for topic patterns
            topic_matches = re.findall(r'##\s*(?:Topic\s*\d+:?\s*)?(.+?)(?:\n|$)', content, re.IGNORECASE)
            if topic_matches:
                metadata["topics"] = [topic.strip() for topic in topic_matches[:5]]  # Limit to first 5 topics
            
            # Look for main title
            title_match = re.search(r'^#\s*(.+)$', content, re.MULTILINE)
            if title_match:
                metadata["title"] = title_match.group(1).strip()
        
        return metadata
    
    def process_all_files(self) -> List[Dict[str, Any]]:
        """Process all files in the data directory."""
        all_chunks = []
        
        if not self.data_dir.exists():
            print(f"Data directory {self.data_dir} does not exist!")
            return all_chunks
        
        # Get all supported files
        supported_extensions = ['.md', '.txt', '.pdf', '.docx', '.doc']
        files = []
        for ext in supported_extensions:
            files.extend(self.data_dir.glob(f"*{ext}"))
            files.extend(self.data_dir.glob(f"**/*{ext}"))
        
        print(f"Found {len(files)} files to process")
        
        for file_path in sorted(files):
            print(f"Processing: {file_path}")
            
            # Extract metadata
            metadata = self.extract_metadata(file_path)
            
            # Read file content
            content = self.read_file(file_path)
            
            if not content:
                print(f"No content found in {file_path}")
                continue
            
            # Chunk the content
            chunks = self.chunk_text(content, metadata)
            
            print(f"Created {len(chunks)} chunks from {file_path.name}")
            all_chunks.extend(chunks)
        
        return all_chunks
    
    def upload_to_pinecone(self, chunks: List[Dict[str, Any]], batch_size: int = 50):
        """Upload chunks to Pinecone in batches with embeddings."""
        if not chunks:
            print("No chunks to upload!")
            return
        
        print(f"Uploading {len(chunks)} chunks to Pinecone...")
        
        # Prepare vectors for Pinecone with embeddings
        vectors = []
        for i, chunk in enumerate(chunks):
            vector_id = f"{chunk['metadata']['filename'].replace('.', '_')}_{chunk['metadata']['chunk_index']}"
            
            # Generate embedding for the chunk text using our simple method
            embedding = create_simple_embedding(chunk["text"])
            
            vectors.append({
                "id": vector_id,
                "values": embedding.tolist(),  # Convert numpy array to list
                "metadata": {
                    **chunk["metadata"],
                    "chunk_text": chunk["text"]  # Keep text in metadata for search results
                }
            })
        
        # Upload in batches
        total_uploaded = 0
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            
            try:
                # Upsert batch to Pinecone
                response = index.upsert(
                    vectors=batch,
                    namespace="iqed-content"
                )
                total_uploaded += len(batch)
                print(f"Uploaded batch {i//batch_size + 1}: {len(batch)} vectors (Total: {total_uploaded})")
                
            except Exception as e:
                print(f"Error uploading batch {i//batch_size + 1}: {e}")
                continue
        
        print(f"Upload completed! Total vectors uploaded: {total_uploaded}")
        
        # Show final index stats
        final_stats = index.describe_index_stats()
        print(f"Final index stats: {final_stats}")
    
    def vectorize_all_data(self):
        """Main method to process all files and upload to Pinecone."""
        print("Starting data vectorization process...")
        
        # Process all files
        chunks = self.process_all_files()
        
        if not chunks:
            print("No chunks were created. Exiting.")
            return
        
        print(f"Total chunks created: {len(chunks)}")
        
        # Upload to Pinecone
        self.upload_to_pinecone(chunks)
        
        print("Vectorization process completed!")

# Main execution
if __name__ == "__main__":
    # Create vectoriser instance
    vectoriser = DataVectoriser(
        data_dir="data",
        chunk_size=1000,  # Adjust based on your needs
        chunk_overlap=200  # Adjust based on your needs
    )
    
    # Run vectorization
    vectoriser.vectorize_all_data()