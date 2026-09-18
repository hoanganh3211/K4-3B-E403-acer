import os
import uuid
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, 
    Filter, FieldCondition, MatchValue, MatchAny,
    PayloadSchemaType
)
from sentence_transformers import SentenceTransformer
import openai

class QdrantVietnameseStore:
    COLLECTION_NAME = "scriptscout_vietnamese_evidence"

    def __init__(
        self, 
        qdrant_url: str = "http://localhost:6333",
        use_openai: bool = False
    ):
        """
        Kết nối tới Qdrant chạy trên Docker (http://localhost:6333).
        - use_openai=False: Dùng BAAI/bge-m3 (SOTA Tiếng Việt, 1024 dims, miễn phí).
        - use_openai=True: Dùng text-embedding-3-large (3072 dims, Cloud API).
        """
        self.client = QdrantClient(url=qdrant_url)
        self.use_openai = use_openai

        if self.use_openai:
            self.vector_size = 3072
            self.openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            print("👑 Đang sử dụng Embedding: OpenAI text-embedding-3-large (3072 dims)")
        else:
            self.vector_size = 1024
            # Model đỉnh cao nhất cho ngữ nghĩa tiếng Việt: BAAI/bge-m3
            print("🇻🇳 Đang tải model embedding tiếng Việt SOTA: BAAI/bge-m3...")
            self.embed_model = SentenceTransformer("BAAI/bge-m3")
            print("✅ Đã sẵn sàng BAAI/bge-m3 (1024 dims)!")

        self._init_collection()

    def _init_collection(self):
        """Tạo collection và đánh Index cho metadata để query tốc độ cao"""
        collections = [c.name for c in self.client.get_collections().collections]
        if self.COLLECTION_NAME not in collections:
            self.client.create_collection(
                collection_name=self.COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=self.vector_size, 
                    distance=Distance.COSINE
                ),
            )
            # Tạo Index cho source_id để khi lọc/xóa nguồn (Local Patch) đạt tốc độ mili-giây
            self.client.create_payload_index(
                collection_name=self.COLLECTION_NAME,
                field_name="source_id",
                field_schema=PayloadSchemaType.KEYWORD
            )
            print(f"✅ Đã khởi tạo Qdrant Collection: {self.COLLECTION_NAME}")

    def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Sinh vector embedding tiếng Việt chuẩn xác"""
        if self.use_openai:
            resp = self.openai_client.embeddings.create(
                model="text-embedding-3-large",
                input=texts
            )
            return [data.embedding for data in resp.data]
        else:
            # Sửa thành .encode() cho SentenceTransformer (chuẩn hóa Cosine Similarity)
            embeddings = self.embed_model.encode(texts, normalize_embeddings=True)
            return embeddings.tolist()

    def _chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
        """Cắt văn bản tiếng Việt thành các đoạn nhỏ có ngữ cảnh gối đầu"""
        words = text.split()
        chunks = []
        for i in range(0, len(words), chunk_size - overlap):
            chunk = " ".join(words[i:i + chunk_size])
            if len(chunk.strip()) > 30:
                chunks.append(chunk.strip())
        return chunks

    def ingest_sources(self, raw_sources: List[Dict[str, Any]]):
        """Đưa toàn bộ tài liệu web vào Docker Qdrant kèm Metadata chi tiết"""
        all_chunks = []
        all_payloads = []

        for src in raw_sources:
            source_id = src.get("source_id")
            url = src.get("url", "")
            title = src.get("title", "")
            author = src.get("author", "Không rõ")
            published_date = src.get("published_date", "")
            raw_markdown = src.get("raw_markdown", "")

            chunks = self._chunk_text(raw_markdown)
            for idx, chunk in enumerate(chunks):
                all_chunks.append(chunk)
                all_payloads.append({
                    "source_id": source_id,
                    "chunk_id": f"{source_id}_{idx}",
                    "url": url,
                    "title": title,
                    "author": author,
                    "published_date": published_date,
                    "text": chunk
                })

        if not all_chunks:
            return

        print(f"🔄 Đang vector hóa {len(all_chunks)} đoạn văn bản tiếng Việt...")
        embeddings = self._get_embeddings(all_chunks)

        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=emb,
                payload=payload
            )
            for emb, payload in zip(embeddings, all_payloads)
        ]

        # Đẩy dữ liệu vào Docker Qdrant
        self.client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=points
        )
        print(f"🚀 Đã nạp thành công {len(points)} vector vào Docker Qdrant!")

    def search_evidence(
        self, 
        query: str, 
        top_k: int = 3, 
        active_source_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Truy vấn ngữ nghĩa tiếng Việt:
        Tìm chính xác đoạn trích dẫn chứng minh cho một luận điểm
        """
        if active_source_ids is not None and not active_source_ids:
            return []
        query_vector = self._get_embeddings([query])[0]
        # Bộ lọc Payload: Chỉ tìm trong các nguồn người duyệt đã chọn giữ lại
        query_filter = None
        if active_source_ids:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="source_id",
                        match=MatchAny(any=active_source_ids)
                    )
                ]
            )
        # Hỗ trợ cả bản qdrant-client mới nhất (query_points) và bản cũ (search)
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=self.COLLECTION_NAME,
                query=query_vector,
                limit=top_k,
                query_filter=query_filter
            )
            search_results = response.points
        else:
            search_results = self.client.search(
                collection_name=self.COLLECTION_NAME,
                query_vector=query_vector,
                limit=top_k,
                query_filter=query_filter
            )
        results = []
        for hit in search_results:
            results.append({
                "score": round(hit.score, 3),
                "source_id": hit.payload.get("source_id"),
                "snippet_quote": hit.payload.get("text"),
                "url": hit.payload.get("url"),
                "title": hit.payload.get("title")
            })
        return results

    def delete_source_vectors(self, source_id: str):
        """
        CƠ CHẾ VÁ CỤC BỘ (LOCAL PATCH):
        Xóa ngay lập tức tất cả vector của nguồn bị reject khỏi Docker Qdrant
        """
        self.client.delete(
            collection_name=self.COLLECTION_NAME,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="source_id",
                        match=MatchValue(value=source_id)
                    )
                ]
            )
        )
        print(f"🗑️ Đã xóa toàn bộ vector của nguồn '{source_id}' khỏi Docker Qdrant!")
