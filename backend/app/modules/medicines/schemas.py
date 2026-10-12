from app.core.schemas import CamelModel


class MedicineSummary(CamelModel):
    id: str
    name: str
    maker: str
    category: str
    type: str  # 일반 | 전문


class MedicineDetail(MedicineSummary):
    efficacy: str
    usage: str
    precautions: str
    interaction_summary: str
    source: str
