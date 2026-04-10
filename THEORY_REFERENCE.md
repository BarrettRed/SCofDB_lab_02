# Справочник теории для защиты лабораторной работы №2
## Управление конкурентными транзакциями в СУБД

---

## 📚 Раздел 1: Транзакции и ACID

### 1.1. Что такое транзакция?

**Транзакция** — это последовательность операций с БД, которая выполняется как единое целое.

**Пример:**
```sql
BEGIN;
  UPDATE accounts SET balance = balance - 100 WHERE id = 1;
  UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;
```

### 1.2. Свойства ACID

| Свойство | Описание | Пример нарушения |
|----------|----------|------------------|
| **A**tomicity (Атомарность) | Все или ничего | Частичное обновление данных |
| **C**onsistency (Согласованность) | Переход из одного валидного состояния в другое | Нарушение ограничений БД |
| **I**solation (Изоляция) | Транзакции не влияют друг на друга | Race condition |
| **D**urability (Долговечность) | После COMMIT изменения сохраняются | Потеря данных после сбоя |

**Вопрос для защиты:** Какое свойство ACID нарушается при race condition?

**Ответ:** **Isolation (Изоляция)** — параллельные транзакции влияют на результат друг друга.

---

## 📚 Раздел 2: Аномалии параллельного доступа

### 2.1. Dirty Read (Грязное чтение)

**Определение:** Чтение незакоммиченных данных другой транзакции.

**Сценарий:**
```
Время | Сессия 1                    | Сессия 2
------|----------------------------|---------------------------
t1    | BEGIN                      |
t2    | UPDATE accounts            |
      | SET balance = 500          |
t3    |                            | BEGIN
t4    |                            | SELECT balance  ← Читает 500!
t5    | ROLLBACK                   |
t6    |                            | COMMIT
```

**Результат:** Сессия 2 прочитала данные (500), которые никогда не существовали (откачены).

---

### 2.2. Non-Repeatable Read (Неповторяемое чтение)

**Определение:** Повторный SELECT в той же транзакции возвращает другие данные.

**Сценарий:**
```
Время | Сессия 1                    | Сессия 2
------|----------------------------|---------------------------
t1    | BEGIN                      |
t2    | SELECT balance = 1000      |
t3    |                            | BEGIN
t4    |                            | UPDATE balance = 500
t5    |                            | COMMIT
t6    | SELECT balance = 500  ← !  |
t7    | COMMIT                     |
```

**Результат:** В одной транзакции один и тот же запрос дал разные результаты.

---

### 2.3. Phantom Read (Фантомное чтение)

**Определение:** Повторный SELECT с условием возвращает другое количество строк.

**Сценарий:**
```
Время | Сессия 1                    | Сессия 2
------|----------------------------|---------------------------
t1    | BEGIN                      |
t2    | SELECT * FROM orders       |
      | WHERE status = 'created'   |  ← 5 строк
t3    |                            | BEGIN
t4    |                            | INSERT INTO orders 
      |                            | VALUES (..., 'created')
t5    |                            | COMMIT
t6    | SELECT * FROM orders       |
      | WHERE status = 'created'   |  ← 6 строк (фантом!)
t7    | COMMIT                     |
```

**Результат:** Появилась новая строка, которой не было в начале транзакции.

---

### 2.4. Write Skew (Перекошенное обновление)

**Определение:** Две транзакции читают пересекающиеся данные, принимают решения на основе прочитанного и обновляют непересекающиеся данные.

**Классический пример:**
```sql
-- Правило: хотя бы один дежурный врач должен быть на смене

-- Сессия 1                         -- Сессия 2
BEGIN;                              BEGIN;
SELECT COUNT(*) FROM doctors        SELECT COUNT(*) FROM doctors
WHERE on_call = true;  -- 2         WHERE on_call = true;  -- 2
                                    -- ОБЕ видят 2 врача
UPDATE doctors                      UPDATE doctors
SET on_call = false                 SET on_call = false
WHERE name = 'Alice';               WHERE name = 'Bob';
COMMIT;                             COMMIT;
```

**Результат:** После COMMIT на смене **0 врачей** (нарушение правила).

---

## 📚 Раздел 3: Уровни изоляции SQL Standard

### 3.1. Таблица уровней изоляции

| Уровень изоляции | Dirty Read | Non-Repeatable Read | Phantom Read |
|------------------|------------|---------------------|--------------|
| **READ UNCOMMITTED** | Возможна | Возможна | Возможна |
| **READ COMMITTED** | ✅ Нет | Возможна | Возможна |
| **REPEATABLE READ** | ✅ Нет | ✅ Нет | Возможна* |
| **SERIALIZABLE** | ✅ Нет | ✅ Нет | ✅ Нет |

_*В PostgreSQL REPEATABLE READ также предотвращает Phantom Read благодаря MVCC_

---

### 3.2. READ UNCOMMITTED

**Описание:** Самый низкий уровень. Транзакции видят незакоммиченные изменения других.

**В PostgreSQL:** Фактически работает как **READ COMMITTED** из-за архитектуры MVCC.

**Когда использовать:**
- ✅ Аналитические запросы (приблизительные данные)
- ✅ Статистика в реальном времени
- ❌ Финансовые операции
- ❌ Критичные данные

**Пример:**
```sql
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;
BEGIN;
SELECT * FROM orders;  -- Может увидеть незакоммиченные данные
COMMIT;
```

---

### 3.3. READ COMMITTED (по умолчанию в PostgreSQL)

**Описание:** Каждый SELECT видит snapshot на момент **начала запроса**.

**Гарантии:**
- ✅ Нет Dirty Read
- ❌ Возможно Non-Repeatable Read
- ❌ Возможен Phantom Read

**Когда использовать:**
- ✅ Обычные CRUD-операции
- ✅ Просмотр данных пользователем
- ✅ 90% веб-приложений

**Пример проблемы:**
```sql
-- Сессия 1
BEGIN;
SELECT balance FROM accounts WHERE id = 1;  -- 1000
-- Сессия 2 делает COMMIT изменения
SELECT balance FROM accounts WHERE id = 1;  -- 500 (другое значение!)
COMMIT;
```

---

### 3.4. REPEATABLE READ

**Описание:** Транзакция видит snapshot на момент **первого запроса** в транзакции.

**Гарантии:**
- ✅ Нет Dirty Read
- ✅ Нет Non-Repeatable Read
- ✅ Нет Phantom Read (в PostgreSQL!)

**Когда использовать:**
- ✅ Отчёты за период
- ✅ Сложные вычисления внутри транзакции
- ✅ Критичные операции с блокировками (FOR UPDATE)

**Пример:**
```sql
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT balance FROM accounts WHERE id = 1;  -- Snapshot зафиксирован
-- Сессия 2 делает COMMIT изменения
SELECT balance FROM accounts WHERE id = 1;  -- Всё ещё 1000!
COMMIT;
```

**Особенность PostgreSQL:** Благодаря **MVCC** предотвращает Phantom Read, хотя стандарт SQL допускает его.

---

### 3.5. SERIALIZABLE

**Описание:** Самый строгий уровень. Параллельные транзакции выполняются так, как если бы были последовательными.

**Гарантии:**
- ✅ Все аномалии предотвращены
- ✅ Нет Write Skew

**Недостатки:**
- ❌ Снижение производительности (20-50%)
- ❌ Возможны ошибки **serialization failure**
- ❌ Требует retry logic

**Когда использовать:**
- ✅ Финансовые переводы
- ✅ Бронирование мест
- ✅ Критичные бизнес-правила

**Пример serialization failure:**
```sql
-- Сессия 1                         -- Сессия 2
BEGIN ISOLATION LEVEL SERIALIZABLE; BEGIN ISOLATION LEVEL SERIALIZABLE;
SELECT SUM(balance) FROM accounts;  SELECT SUM(balance) FROM accounts;
-- 5000                              -- 5000
UPDATE accounts SET balance =       UPDATE accounts SET balance = 
  balance + 100 WHERE id = 1;         balance + 200 WHERE id = 2;
COMMIT;  -- ✅                        COMMIT;  -- ❌ ERROR:
                                    -- could not serialize access
                                    -- due to read/write dependencies
```

---

## 📚 Раздел 4: Блокировки в PostgreSQL

### 4.1. Зачем нужны блокировки?

**Проблема:** Даже на REPEATABLE READ без блокировок возможна аномалия:

```sql
-- Сессия 1                         -- Сессия 2
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT status FROM orders           SELECT status FROM orders
WHERE id = 1;  -- 'created'         WHERE id = 1;  -- 'created'
-- ОБЕ видят 'created'!
UPDATE orders SET status = 'paid'   -- ЖДЁТ блокировку
WHERE id = 1;                       UPDATE orders SET status = 'paid'
COMMIT;                             WHERE id = 1;  -- УСПЕХ!
                                    COMMIT;
-- ИТОГ: ДВЕ записи в истории!
```

**Решение:** Использовать `FOR UPDATE` для блокировки строки.

---

### 4.2. Типы блокировок строк

| Тип блокировки | Блокирует UPDATE | Блокирует DELETE | Блокирует FOR UPDATE | Блокирует FOR SHARE |
|----------------|------------------|------------------|----------------------|---------------------|
| **FOR UPDATE** | ✅ Да | ✅ Да | ✅ Да | ✅ Да |
| **FOR SHARE**  | ✅ Да | ✅ Да | ❌ Нет | ✅ Да |
| **FOR NO KEY UPDATE** | ✅ Да | ✅ Да | ✅ Да | ❌ Нет |
| **FOR KEY SHARE** | ❌ Нет | ✅ Да | ✅ Да | ✅ Да |

---

### 4.3. FOR UPDATE (эксклюзивная блокировка)

**Синтаксис:**
```sql
SELECT * FROM orders WHERE id = 1 FOR UPDATE;
```

**Поведение:**
- Блокирует выбранные строки для других транзакций
- Другие транзакции не могут: UPDATE, DELETE, SELECT ... FOR UPDATE
- Другие транзакции **ждут** освобождения блокировки
- Блокировка снимается при COMMIT или ROLLBACK

**Пример использования:**
```python
async def pay_order(order_id: UUID):
    async with db.transaction(isolation='repeatable_read'):
        # Блокируем заказ
        order = await db.fetch_one(
            "SELECT * FROM orders WHERE id = $1 FOR UPDATE",
            order_id
        )
        
        if order['status'] != 'created':
            raise OrderAlreadyPaidError()
        
        # Теперь безопасно обновлять
        await db.execute(
            "UPDATE orders SET status = 'paid' WHERE id = $1",
            order_id
        )
```

---

### 4.4. FOR SHARE (разделяемая блокировка)

**Синтаксис:**
```sql
SELECT * FROM products WHERE id = 1 FOR SHARE;
```

**Поведение:**
- Несколько транзакций могут одновременно взять FOR SHARE
- Блокирует UPDATE и DELETE
- Не блокирует другие FOR SHARE

**Пример использования:**
```sql
-- Проверка наличия перед созданием заказа
BEGIN;
SELECT quantity FROM products WHERE id = 1 FOR SHARE;
-- Товар не может быть удалён или изменён
INSERT INTO orders (...) VALUES (...);
COMMIT;
```

---

### 4.5. Deadlock (Взаимная блокировка)

**Определение:** Две транзакции ждут друг друга, образуя цикл.

**Сценарий:**
```
Время | Сессия 1                    | Сессия 2
------|----------------------------|---------------------------
t1    | UPDATE orders WHERE id = 1 |
      | (блокировка id=1)          |
t2    |                            | UPDATE orders WHERE id = 2
      |                            | (блокировка id=2)
t3    | UPDATE orders WHERE id = 2 |
      | (ЖДЁТ id=2!)               |
t4    |                            | UPDATE orders WHERE id = 1
      |                            | (ЖДЁТ id=1!)
t5    | ❌ DEADLOCK DETECTED       |
```

**Решение:**
- Всегда блокировать ресурсы в **одном порядке** (например, по возрастанию ID)
- Использовать таймауты
- Обрабатывать ошибку deadlock

---

## 📚 Раздел 5: MVCC в PostgreSQL

### 5.1. Что такое MVCC?

**MVCC (Multi-Version Concurrency Control)** — механизм управления параллельным доступом через хранение нескольких версий строк.

**Принцип работы:**
1. При UPDATE создаётся **новая версия** строки
2. Старая версия сохраняется
3. Каждая транзакция видит только версии, актуальные для её snapshot

**Пример:**
```
Таблица accounts:
id | balance | xmin | xmax
---|---------|------|------
1  | 1000    | 100  | 0      ← версия 1 (создана в txn 100)
1  | 500     | 200  | 0      ← версия 2 (создана в txn 200)

-- Транзакция 150 видит версию 1 (1000)
-- Транзакция 250 видит версию 2 (500)
```

---

### 5.2. Snapshot Isolation

**Snapshot** — моментальное состояние БД на определённый момент времени.

**В READ COMMITTED:**
- Каждый SELECT получает новый snapshot
- Возможны Non-Repeatable Read

**В REPEATABLE READ:**
- Первый SELECT фиксирует snapshot
- Все последующие SELECT используют тот же snapshot
- Гарантировано повторяемое чтение

---

### 5.3. Почему PostgreSQL не имеет Dirty Read?

Благодаря MVCC:
- Транзакция видит только строки с `xmin < current_txn_id`
- Незакоммиченные строки имеют `xmin > current_txn_id` или не имеют `xmax`
- Физически невозможно прочитать незавершённые данные

---

## 📚 Раздел 6: Практическое применение

### 6.1. Выбор уровня изоляции

| Сценарий | Рекомендуемый уровень | Обоснование |
|----------|----------------------|-------------|
| Просмотр каталога | READ COMMITTED | Высокая производительность |
| Корзина покупок | READ COMMITTED | Изоляция не критична |
| Оплата заказа | REPEATABLE READ + FOR UPDATE | Защита от двойной оплаты |
| Перевод между счетами | SERIALIZABLE | Максимальная безопасность |
| Генерация отчёта | REPEATABLE READ | Консистентные данные за период |
| Бронирование мест | REPEATABLE READ + FOR UPDATE | Защита от овербукинга |

---

### 6.2. Паттерн: Оптимистичная блокировка

**Когда использовать:**
- Высокая конкурентность
- Редкие конфликты
- Чтение чаще записи

**Реализация:**
```sql
-- 1. Добавить столбец версии
ALTER TABLE orders ADD COLUMN version INTEGER DEFAULT 1;

-- 2. Обновление с проверкой версии
UPDATE orders
SET status = 'paid', version = version + 1
WHERE id = '...' AND status = 'created' AND version = 5;

-- 3. Проверить ROW_COUNT
-- Если 0 — конфликт, retry или ошибка
```

**Плюсы:**
- ✅ Нет блокировок на чтение
- ✅ Хорошая масштабируемость

**Минусы:**
- ❌ Требует retry logic
- ❌ Изменение схемы БД

---

### 6.3. Паттерн: Advisory Locks

**Когда использовать:**
- Блокировка логических ресурсов
- Кастомные бизнес-правила

**Реализация:**
```sql
-- Блокировка по ключу
SELECT pg_advisory_xact_lock(hashtext('order_' || order_id));

-- Критическая секция
UPDATE orders SET status = 'paid' WHERE id = order_id;

-- Блокировка снимается автоматически при COMMIT
```

**Плюсы:**
- ✅ Гибкий контроль
- ✅ Работает на любом уровне изоляции

**Минусы:**
- ❌ Легко забыть снять
- ❌ Требует дисциплины

---

## 📚 Раздел 7: Вопросы для самопроверки

### Базовые вопросы

1. **Что такое ACID?**
2. **Назовите 4 аномалии параллельного доступа**
3. **Какой уровень изоляции по умолчанию в PostgreSQL?**
4. **В чём разница между Non-Repeatable и Phantom Read?**
5. **Что такое MVCC?**

### Вопросы по уровням изоляции

6. **Какие аномалии предотвращает READ COMMITTED?**
7. **Почему PostgreSQL на REPEATABLE READ не имеет Phantom Read?**
8. **Когда использовать SERIALIZABLE?**
9. **Что такое serialization failure?**
10. **Почему READ UNCOMMITTED в PostgreSQL работает как READ COMMITTED?**

### Вопросы по блокировкам

11. **В чём разница между FOR UPDATE и FOR SHARE?**
12. **Что такое deadlock? Как его избежать?**
13. **Когда снимается блокировка FOR UPDATE?**
14. **Может ли SELECT вызвать блокировку?**
15. **Что такое row-level lock?**

### Вопросы по практике

16. **Почему без FOR UPDATE даже REPEATABLE READ не защищает?**
17. **Как реализовать retry logic для SERIALIZABLE?**
18. **Когда лучше использовать optimistic locking?**
19. **Что такое advisory locks и когда их применять?**
20. **Как выбрать уровень изоляции для интернет-магазина?**

---

## 📚 Раздел 8: Шпаргалка для защиты

### Ключевые тезисы

1. **READ COMMITTED не защищает** от race condition при конкурентных UPDATE
2. **REPEATABLE READ + FOR UPDATE** решает проблему через блокировки
3. **Без FOR UPDATE** даже REPEATABLE READ не гарантирует корректность
4. **MVCC** в PostgreSQL предотвращает Dirty Read на всех уровнях
5. **Для продакшена** рекомендуется гибридный подход

### Типовые вопросы и ответы

**В: Что произойдёт, если убрать FOR UPDATE?**

**О:** Две транзакции прочитают одинаковый статус 'created' и обе выполнят UPDATE → двойная оплата.

---

**В: Почему нельзя использовать SERIALIZABLE везде?**

**О:** Снижение производительности (20-50%), частые serialization failure, требует retry logic.

---

**В: В чём разница между pessimistic и optimistic locking?**

**О:** 
- **Pessimistic (FOR UPDATE):** Блокируем заранее, предполагаем конфликт
- **Optimistic (версионирование):** Проверяем при записи, конфликты редки

---

**В: Что такое Write Skew?**

**О:** Аномалия, когда две транзакции читают пересекающиеся данные, принимают решения и обновляют непересекающиеся строки. Предотвращается только на SERIALIZABLE.

---

**В: Как PostgreSQL реализует REPEATABLE READ?**

**О:** Через MVCC — первый SELECT фиксирует snapshot, все последующие запросы используют ту же версию данных.

---

## 📚 Раздел 9: Дополнительные ресурсы

### Документация

- [PostgreSQL: Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- [PostgreSQL: Explicit Locking](https://www.postgresql.org/docs/current/explicit-locking.html)
- [PostgreSQL: MVCC](https://www.postgresql.org/docs/current/mvcc.html)

### Статьи

- [Designing Data-Intensive Applications — Chapter 7](https://dataintensive.net/)
- [PostgreSQL Wiki: MVCC](https://wiki.postgresql.org/wiki/MVCC)
- [Martin Kleppmann: Race Conditions](https://martin.kleppmann.com/)

### Книги

- "PostgreSQL 14 Internals" — E. Rogov
- "Designing Data-Intensive Applications" — M. Kleppmann
- "Database Internals" — A. Petrov

---

**Объём справочника:** ~2500 слов  
**Время на изучение:** 2-3 часа  
**Уровень:** для успешной защиты на "отлично"
