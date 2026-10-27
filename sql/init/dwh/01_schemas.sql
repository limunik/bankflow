-- Четыре слоя хранилища BankFlow
CREATE SCHEMA IF NOT EXISTS stg;       -- сырые данные как есть
CREATE SCHEMA IF NOT EXISTS ods;       -- очищенные данные с типами
CREATE SCHEMA IF NOT EXISTS dds;       -- модель: факты, измерения,
CREATE SCHEMA IF NOT EXISTS datamart;  -- витрины для аналитики
