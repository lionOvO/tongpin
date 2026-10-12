from .errors import DomainError


class LocalRetrieval:
    def __init__(self, settings):
        self.settings = settings
        self.collection = self.encoder = self.reranker = None

    def initialize(self):
        if self.collection is not None: return
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer, CrossEncoder
            self.encoder = SentenceTransformer("BAAI/bge-m3", device="cpu")
            self.reranker = CrossEncoder("BAAI/bge-reranker-base", device="cpu")
            self.collection = chromadb.PersistentClient(path=str(self.settings.data_dir / "chroma")).get_or_create_collection("resume_chunks")
        except (ImportError, OSError) as exc:
            raise DomainError("VECTOR_UNAVAILABLE", "本地向量检索未就绪，请安装可选依赖并预下载模型", 503) from exc

    def upsert(self, resume):
        if not self.settings.vector: return
        self.initialize()
        chunks = [resume["text"][i:i+600] for i in range(0,len(resume["text"]),500)]
        if not chunks: return
        self.collection.upsert(ids=[resume["id"]+":"+str(i) for i in range(len(chunks))], documents=chunks, embeddings=self.encoder.encode(chunks, normalize_embeddings=True).tolist(), metadatas=[{"resume_id":resume["id"],"owner":resume["owner"],"env":resume["env"],"data_origin":resume["data_origin"]} for _ in chunks])

    def search(self, query, owner, env, origin):
        if not self.settings.vector: return []
        self.initialize()
        count = self.collection.count()
        if not count: return []
        result = self.collection.query(query_embeddings=[self.encoder.encode(query,normalize_embeddings=True).tolist()], n_results=min(20,count),where={"$and":[{"owner":owner},{"env":env},{"data_origin":origin}]})
        docs, metas = result["documents"][0], result["metadatas"][0]
        if not docs: return []
        scores = self.reranker.predict([[query,d] for d in docs])
        return list(dict.fromkeys(metas[i]["resume_id"] for i in sorted(range(len(docs)),key=lambda i:float(scores[i]),reverse=True)))

    def remove(self, ids):
        if not self.settings.vector: return
        self.initialize()
        for id in ids: self.collection.delete(where={"resume_id":id})
