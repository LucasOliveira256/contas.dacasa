from datetime import date
from pydantic import BaseModel, Field, ConfigDict, model_validator

class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class IncomeCreate(BaseModel):
    person_id: int
    kind: str = Field(pattern="^(salario|extra|plano_saude|inss|ir)$")
    happened_on: date
    amount_cents: int = Field(ge=0)
    description: str = ""

class TransactionCreate(BaseModel):
    description: str = Field(min_length=1, max_length=240)
    amount_cents: int = Field(ge=0)
    purchase_date: date
    category_id: int
    person_id: int
    account_id: int | None = None
    card_id: int | None = None
    status: str = Field(default="realizado", pattern="^(previsto|realizado)$")
    installments: int = Field(default=1, ge=1, le=60)
    @model_validator(mode="after")
    def payment_method(self):
        if self.card_id and self.account_id:
            raise ValueError("Escolha cartão ou conta, não ambos.")
        return self

class FixedExpenseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    amount_cents: int = Field(ge=0)
    day_of_month: int = Field(ge=1, le=31)
    category_id: int
    person_id: int
    start_date: date
    end_date: date | None = None
    account_id: int | None = None
    card_id: int | None = None
