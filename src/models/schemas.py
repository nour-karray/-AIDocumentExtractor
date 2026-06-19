from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


AnalysisStatus = Literal["low", "normal", "high", "unknown"]
AnalysisCategory = Literal[
    "hematology",
    "biochemistry",
    "hormonology",
    "serology",
    "immunology",
    "other",
]


class ReferenceRange(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None
    raw_text: Optional[str] = None


class DocumentMetadata(BaseModel):
    exam_number: Optional[str] = None
    dossier_number: Optional[str] = None
    received_date: Optional[str] = None
    edited_date: Optional[str] = None
    request_date: Optional[str] = None
    sample_date: Optional[str] = None
    report_date: Optional[str] = None
    page_number: Optional[str] = None
    organization: Optional[str] = None
    source_file: Optional[str] = None
    document_type: str = "medical_lab_report"


class PatientInfo(BaseModel):
    patient_name: Optional[str] = None
    patient_id: Optional[str] = None
    date_of_birth: Optional[str] = None
    sex: Optional[str] = None


class LabInfo(BaseModel):
    lab_name: Optional[str] = None
    doctor_name: Optional[str] = None


class LabTest(BaseModel):
    raw_test_name: str = ""
    normalized_name: str = "unknown"
    category: AnalysisCategory = "other"
    # Valeur brute (ex. "<5", "positif") si non convertible en float
    value_text: Optional[str] = None
    value: Optional[float] = None
    secondary_value: Optional[float] = None
    previous_value: Optional[float] = None
    unit: Optional[str] = None
    reference_range: Optional[ReferenceRange] = None
    status: AnalysisStatus = "unknown"
    raw_line: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: Optional[str] = None


class ProcessingWarning(BaseModel):
    code: str
    message: str
    context: Optional[str] = None


class MedicalDocumentResult(BaseModel):
    document_type: str = "medical_lab_report"
    lab_info: LabInfo = Field(default_factory=LabInfo)
    patient_info: PatientInfo = Field(default_factory=PatientInfo)
    document_metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    tests: List[LabTest] = Field(default_factory=list)
    warnings: List[ProcessingWarning] = Field(default_factory=list)
    raw_text: Optional[str] = None
    # ocr | gemini | hybrid — pour l'UI
    extraction_source: Optional[str] = None


class GeminiMedicalAnalysisRow(BaseModel):
    """Une ligne d'analyse telle que renvoyée par Gemini (page simple)."""

    model_config = ConfigDict(extra="ignore")

    test_name: Optional[str] = None
    value: Optional[str] = None
    unit: Optional[str] = None

    @field_validator("test_name", "value", "unit", mode="before")
    @classmethod
    def _empty_to_none(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or None


class GeminiMedicalPagePayload(BaseModel):
    """Schéma strict pour la sortie vision « page simple » analyses médicales."""

    model_config = ConfigDict(extra="ignore")

    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    date: Optional[str] = None
    analyses: List[GeminiMedicalAnalysisRow] = Field(default_factory=list)

    @field_validator("patient_name", "doctor_name", "date", mode="before")
    @classmethod
    def _header_str(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or None


class ReceiptLineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: Optional[str] = None
    quantity: Optional[str] = None
    unit_price: Optional[str] = None
    line_total: Optional[str] = None

    @field_validator("description", "quantity", "unit_price", "line_total", mode="before")
    @classmethod
    def _line_str(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or None


class ReceiptGeminiPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    store_name: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    ticket_number: Optional[str] = None
    currency: Optional[str] = None
    items: List[ReceiptLineItem] = Field(default_factory=list)
    total: Optional[str] = None
    payment_method: Optional[str] = None

    @field_validator(
        "store_name",
        "date",
        "time",
        "ticket_number",
        "currency",
        "total",
        "payment_method",
        mode="before",
    )
    @classmethod
    def _hdr_str(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or None


class SupplierInvoiceSellerParty(BaseModel):
    """Fournisseur / vendeur."""

    model_config = ConfigDict(extra="ignore")

    name: str = ""
    address: str = ""
    tax_id: str = ""
    iban: str = ""
    email: str = ""
    phone: str = ""

    @field_validator("name", "address", "tax_id", "iban", "email", "phone", mode="before")
    @classmethod
    def _blank_str(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()


class SupplierInvoiceClientParty(BaseModel):
    """Client / acheteur."""

    model_config = ConfigDict(extra="ignore")

    name: str = ""
    address: str = ""
    tax_id: str = ""
    email: str = ""
    phone: str = ""

    @field_validator("name", "address", "tax_id", "email", "phone", mode="before")
    @classmethod
    def _blank_str(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()


class SupplierInvoiceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str = ""
    quantity: str = ""
    unit: str = ""
    unit_price: str = ""
    net_amount: str = ""
    tax_rate: str = ""
    tax_amount: str = ""
    gross_amount: str = ""

    @field_validator(
        "description",
        "quantity",
        "unit",
        "unit_price",
        "net_amount",
        "tax_rate",
        "tax_amount",
        "gross_amount",
        mode="before",
    )
    @classmethod
    def _blank_str(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()


class SupplierInvoiceSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subtotal: str = ""
    tax_total: str = ""
    discount: str = ""
    shipping: str = ""
    total_amount: str = ""
    amount_due: str = ""

    @field_validator(
        "subtotal",
        "tax_total",
        "discount",
        "shipping",
        "total_amount",
        "amount_due",
        mode="before",
    )
    @classmethod
    def _blank_str(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()


class SupplierInvoiceGeminiPayload(BaseModel):
    """Schéma cible facture fournisseur générique (sortie normalisée, JSON anglais)."""

    model_config = ConfigDict(extra="ignore")

    document_type: str = "supplier_invoice"
    invoice_number: str = ""
    invoice_date: str = ""
    due_date: str = ""
    currency: str = ""
    seller: SupplierInvoiceSellerParty = Field(default_factory=SupplierInvoiceSellerParty)
    client: SupplierInvoiceClientParty = Field(default_factory=SupplierInvoiceClientParty)
    items: List[SupplierInvoiceItem] = Field(default_factory=list)
    summary: SupplierInvoiceSummary = Field(default_factory=SupplierInvoiceSummary)
    confidence: str = ""
    missing_fields: List[str] = Field(default_factory=list)
    raw_notes: str = ""

    @field_validator(
        "document_type",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency",
        "confidence",
        "raw_notes",
        mode="before",
    )
    @classmethod
    def _top_str(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("missing_fields", mode="before")
    @classmethod
    def _missing_list(cls, v: object) -> List[str]:
        if not isinstance(v, list):
            return []
        out: List[str] = []
        for x in v:
            if x is None:
                continue
            s = str(x).strip()
            if s:
                out.append(s)
        return out

    @field_validator("seller", mode="before")
    @classmethod
    def _seller(cls, v: object) -> Any:
        if isinstance(v, dict):
            return v
        return {}

    @field_validator("client", mode="before")
    @classmethod
    def _client(cls, v: object) -> Any:
        if isinstance(v, dict):
            return v
        return {}

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, v: object) -> Any:
        if isinstance(v, dict):
            return v
        return {}

    @field_validator("items", mode="before")
    @classmethod
    def _items(cls, v: object) -> List[Any]:
        if not isinstance(v, list):
            return []
        return [x for x in v if isinstance(x, dict)]


class StegGeminiPayload(BaseModel):
    """Champs STEG extraits (Gemini ou structure alignée pour validation)."""

    model_config = ConfigDict(extra="ignore")

    reference: Optional[str] = None
    montant_a_payer: Optional[str] = None
    date_limite_paiement: Optional[str] = None
    periode_du: Optional[str] = None
    periode_au: Optional[str] = None
    coupon_reference_raw: Optional[str] = None
    coupon_montant: Optional[str] = None
    confidence_note: Optional[str] = None

    @field_validator(
        "reference",
        "montant_a_payer",
        "date_limite_paiement",
        "periode_du",
        "periode_au",
        "coupon_reference_raw",
        "coupon_montant",
        "confidence_note",
        mode="before",
    )
    @classmethod
    def _steg_str(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

