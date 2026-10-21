from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Person, Category

PEOPLE = ["Marido", "Esposa", "Família"]
CATEGORIES = {
    "Moradia": ["Aluguel/Financiamento", "Condomínio", "Energia elétrica", "Água", "Internet", "Gás", "Reparos"],
    "Alimentação": ["Supermercado", "Feira", "Restaurante/Delivery", "Lanches"],
    "Educação/Colégio": ["Mensalidade", "Material escolar", "Uniforme", "Eventos/Passeios", "Transporte escolar"],
    "Saúde": ["Farmácia", "Consultas/Exames", "Odontologia", "Plano de saúde (informativo)"],
    "Transporte/Onix": ["Combustível", "Seguro", "IPVA/Licenciamento", "Manutenção", "Estacionamento/Pedágio", "Lavagem"],
    # Lazer fica sem subcategorias para que a descrição livre informe o tipo de gasto.
    "Lazer": [],
    "Filha": ["Roupas/Calçados", "Brinquedos", "Atividades", "Festas/Presentes"],
    "Assinaturas": ["Streaming", "Software/Apps", "Telefonia"],
    "Impostos": ["IR (informativo)", "INSS (informativo)", "Taxas e tributos"],
    "Poupança": [],
    "Outros": ["Presentes", "Serviços", "Animais de estimação", "Diversos"],
}


def _migrate_lazer_categories(db: Session) -> None:
    """Desativa a taxonomia antiga de moto sem apagar referências históricas."""
    old_root = db.scalar(select(Category).where(Category.name == "Lazer/Moto", Category.parent_id.is_(None)))
    lazer_root = db.scalar(select(Category).where(Category.name == "Lazer", Category.parent_id.is_(None)))
    if old_root:
        if not lazer_root:
            old_root.name = "Lazer"
            lazer_root = old_root
        else:
            old_root.active = False
        for child in db.scalars(select(Category).where(Category.parent_id == old_root.id)).all():
            child.active = False
    for category in db.scalars(select(Category).where(Category.name.ilike("%moto%"))).all():
        category.active = False


def seed_database(db: Session) -> None:
    # Pessoas padrão são inseridas só em banco vazio; renomeações/exclusões não são desfeitas no próximo boot.
    if not db.scalar(select(Person.id).limit(1)):
        for name in PEOPLE:
            db.add(Person(name=name))
        db.flush()
    _migrate_lazer_categories(db)
    roots = {c.name: c for c in db.scalars(select(Category).where(Category.parent_id.is_(None))).all()}
    for root_name, children in CATEGORIES.items():
        root = roots.get(root_name)
        if root is None:
            root = Category(name=root_name)
            db.add(root)
            db.flush()
        existing_children = set(db.scalars(select(Category.name).where(Category.parent_id == root.id)).all())
        for child_name in children:
            if child_name not in existing_children:
                db.add(Category(name=child_name, parent_id=root.id))
    db.commit()
