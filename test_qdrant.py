"""Optional manual Qdrant smoke test; never executes during test collection."""


def main():
    from services.qdrant_service import QdrantVietnameseStore
    from sentence_transformers import SentenceTransformer

    # 1. Khởi tạo kết nối tới Docker Qdrant với BAAI/bge-m3
    store = QdrantVietnameseStore(qdrant_url="http://localhost:6333", use_openai=False)

    # 2. Dữ liệu giả lập 2 nguồn cào từ web
    sample_sources = [
        {
            "source_id": "src_01",
            "url": "https://vinai.io/research",
            "title": "Nghiên cứu thị giác máy tính và xe tự hành tại Việt Nam",
            "author": "Viện Nghiên cứu VinAI",
            "published_date": "2025-01-10",
            "raw_markdown": (
                "Hệ thống tự hành áp dụng mô hình Transformer đa tầng giúp nhận diện "
                "xe máy và chướng ngại vật phức tạp trên đường phố Hà Nội với độ chính xác đạt 94.8%."
            )
        },
        {
            "source_id": "src_02",
            "url": "https://baocongnghe.vn/ai-y-te",
            "title": "Ứng dụng trí tuệ nhân tạo trong nội soi",
            "author": "Bệnh viện Chợ Rẫy",
            "published_date": "2024-12-05",
            "raw_markdown": (
                "Phần mềm chẩn đoán hình ảnh hỗ trợ bác sĩ phát hiện polyp sớm, "
                "giúp giảm thiểu 30% thời gian hội chẩn cho các ca bệnh phức tạp."
            )
        }
    ]

    # 3. Nạp dữ liệu vào Qdrant
    store.ingest_sources(sample_sources)

    # 4. Truy vấn ngữ nghĩa tiếng Việt (Dù câu hỏi dùng từ khác, model vẫn tìm đúng nguồn liên quan!)
    query = "Xe không người lái di chuyển trên đường phố đông đúc ở Việt Nam"
    print(f"\n🔍 Đang tìm kiếm bằng chứng cho: '{query}'")
    results = store.search_evidence(query=query, top_k=1)

    for r in results:
        print(f"👉 Điểm tương đồng: {r['score']}")
        print(f"👉 Nguồn: [{r['source_id']}] {r['title']}")
        print(f"👉 Trích dẫn: \"{r['snippet_quote']}\"")

if __name__ == "__main__":
    main()
