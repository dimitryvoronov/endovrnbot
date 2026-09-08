"""Profile choices + calorie estimate (Mifflin-St Jeor x activity factor)."""

SEX_CHOICES = ["Мужской", "Женский"]

# label -> physical activity level (PAL). Generic Mifflin factors.
ACTIVITY_PAL = {
    "Низкая (сидячая работа)": 1.2,
    "Лёгкая активность": 1.375,
    "Средняя активность": 1.55,
    "Высокая активность": 1.725,
    "Очень высокая (тяжёлый физ. труд)": 1.9,
}
ACTIVITY_CHOICES = list(ACTIVITY_PAL)


def estimate_kcal(sex, age, height_cm, weight_kg, activity):
    if not (sex and age and height_cm and weight_kg):
        return None
    s = 5 if str(sex).strip().lower().startswith("м") else -161
    bmr = 10 * float(weight_kg) + 6.25 * float(height_cm) - 5 * int(age) + s
    return round(bmr * ACTIVITY_PAL.get(activity, 1.55))


def bmi(height_cm, weight_kg):
    if not (height_cm and weight_kg):
        return None
    return round(float(weight_kg) / (float(height_cm) / 100) ** 2, 1)
