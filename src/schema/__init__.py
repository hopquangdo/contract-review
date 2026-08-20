"""Schema Pydantic dùng chung cho toàn bộ src/ - mọi structured output của LLM và cấu trúc dữ liệu
nghiệp vụ độc lập với hạ tầng (Neo4j, LLM, HTTP) được khai báo tập trung ở đây, tách khỏi module
gọi LLM/service tương ứng để dễ tìm và tránh vòng lặp import."""
