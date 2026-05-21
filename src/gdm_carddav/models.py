from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Double, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.elements import quoted_name


class Base(DeclarativeBase):
    pass


class People(Base):
    # Quoted to match the PostgreSQL table created with uppercase "People".
    __tablename__ = quoted_name("People", True)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prenom: Mapped[str] = mapped_column(String(255))
    nom: Mapped[str] = mapped_column(String(255))
    # enum_People_sexe stored as text via asyncpg codec registration
    sexe: Mapped[str] = mapped_column(String)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    tel: Mapped[Optional[str]] = mapped_column(String(255))
    photo: Mapped[Optional[str]] = mapped_column(String(255))
    adresse: Mapped[Optional[str]] = mapped_column(String(255))
    ville: Mapped[Optional[str]] = mapped_column(String(255))
    codePostal: Mapped[Optional[str]] = mapped_column(String(255))
    adresse2: Mapped[Optional[str]] = mapped_column(String(255))
    ville2: Mapped[Optional[str]] = mapped_column(String(255))
    codePostal2: Mapped[Optional[str]] = mapped_column(String(255))
    latitude: Mapped[Optional[float]] = mapped_column(Double)
    longitude: Mapped[Optional[float]] = mapped_column(Double)
    dateNaissance: Mapped[Optional[str]] = mapped_column(String(255))
    lieuNaissance: Mapped[Optional[str]] = mapped_column(String(255))
    estDecede: Mapped[Optional[bool]] = mapped_column(Boolean)
    dateDeces: Mapped[Optional[str]] = mapped_column(String(255))
    estMarie: Mapped[Optional[bool]] = mapped_column(Boolean)
    dateMariage: Mapped[Optional[str]] = mapped_column(String(255))
    metier: Mapped[Optional[str]] = mapped_column(String(255))
    notes: Mapped[Optional[str]] = mapped_column(String(250))
    # enum_People_status stored as text via asyncpg codec registration
    status: Mapped[Optional[str]] = mapped_column(String)
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True))
