# Higgsfield Workflows

## WORKFLOW 1: Генерація 4х зображень для вибору референсного (PRIMARY)

### Кроки:

1. **Перевірити чи є референс. Якщо є - Видалити референс.**

2. **Перевірити чи є промпт. Якщо є - видалити.**

3. **В поле для промпту вставити промпт.**
   - Селектор: `textarea[name="prompt"]`

4. **Вибрати ratio (aspect ratio)**

5. **Натиснути на селектор резолюції і вибрати "2K Unlimited":**
   - Селектор кнопки: `button[aria-labelledby*="react-aria"]` з текстом "2K"
   - Вибрати опцію: `div` з текстом "2K" та "Unlimited"
   ```html
   <button aria-haspopup="listbox" class="...">
     <span>2K</span>
   </button>
   ```
   - Вибрати:
   ```html
   <div class="flex flex-1 items-center gap-2...">
     <div>2K <span>Unlimited</span></div>
     <span>Balanced · Recommended for most use cases</span>
   </div>
   ```

6. **Натиснути на "+" (якщо є така можливість) і вибрати 4 зображення**

7. **Натиснути кнопку "генерація" (Generate)**

---

## WORKFLOW 2: Генерація сцени БЕЗ референсу (INDEPENDENT)

### Кроки:

1. **Видаляємо старий промпт**

2. **Вставляємо промпт потрібної сцени**
   - Селектор: `textarea[name="prompt"]`

3. **Натискаємо на Unlimited (в положення ON)**

4. **Натискаємо на кнопку вибору якості зображення і вибираємо 2K**
   - Селектор: `button[aria-haspopup="listbox"]` з текстом "2K"

5. **Натискаємо на кнопку "Генерація" (Generate)**

---

## WORKFLOW 3: Генерація сцени З референсом (REQUIRES_REF)

### Кроки:

1. **Додаємо референс в поле для референсу**
   - Натиснути кнопку "+" для завантаження референсу
   - Завантажити файл зображення

2. **Видаляємо старий промпт, додаємо новий**
   - Селектор: `textarea[name="prompt"]`

3. **Натискаємо на кнопку "Генерація" (Generate)**

---

## WORKFLOW 4: Генерація відео (VIDEO)

### Попередні умови:
- Перейти на вкладку відео
- Вибрати модель Kling

### Кроки:

1. **Перевірити чи є зображення в полі image. Якщо є - видалити:**
   - Кнопка видалення: `button.button--fixed` з SVG path для "X"
   ```html
   <button type="button" class="...button--fixed bg-neutral-surface! size-5! rounded-md!">
     <svg><!-- X icon --></svg>
   </button>
   ```

2. **Завантажити зображення відповідної сцени:**
   - Поле для завантаження: `input#imageUrl` (type="file")
   - Контейнер: `div` з `border-dashed` і "Optional" текстом
   ```html
   <input accept="image/jpeg, image/jpg, image/png, image/webp"
          class="file-input sr-only" id="imageUrl" type="file">
   ```

3. **Видалити старий промпт і вставити новий:**
   - Селектор: `textarea#prompt`
   ```html
   <textarea id="prompt" class="..." placeholder="Describe the scene you imagine...">
   ```

4. **Перевірити/встановити довжину анімації (10s):**
   - Натиснути на Duration selector: `button[aria-label="Duration"]`
   - Вибрати 10s: `div[role="option"][data-key="10"]`
   ```html
   <button aria-label="Duration" aria-haspopup="listbox">
     <span>Duration</span>
     <span>5s</span> <!-- поточне значення -->
   </button>
   <!-- Після кліку вибрати: -->
   <div role="option" data-key="10"><span>10s</span></div>
   ```

5. **Натиснути кнопку "Генерація" (Generate)**

---

## Технічні деталі

### Селектори елементів:

| Елемент | Селектор |
|---------|----------|
| Textarea промпту | `textarea[name="prompt"]` або `textarea.reference-prompt` |
| Кнопка референсу "+" | `button.button--fixed` з SVG path що містить `V4.16602` |
| Кнопка видалення референсу "X" | `button.button--fixed` з SVG path БЕЗ `V4.16602` |
| Селектор резолюції | `button[aria-haspopup="listbox"]` з текстом "2K" |
| Кнопка генерації | TBD |

### Важливі примітки:

- React не бачить зміни `textarea.value` через JavaScript - потрібно використовувати clipboard (Ctrl+V)
- Кнопка "+" і "X" мають однаковий клас `button--fixed`, розрізняються по SVG path
