from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_sitesettings_footer_script"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="allow_recommendations",
            field=models.BooleanField(default=True),
        ),
        migrations.CreateModel(
            name="ProfileRecommendation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("note", models.CharField(blank=True, max_length=140)),
                ("position", models.PositiveSmallIntegerField()),
                ("recommended", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="recommended_by", to="accounts.user")),
                ("recommender", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="recommendation_entries", to="accounts.user")),
            ],
            options={
                "ordering": ["position"],
                "constraints": [
                    models.UniqueConstraint(fields=("recommender", "recommended"), name="unique_profile_recommendation"),
                    models.UniqueConstraint(fields=("recommender", "position"), name="unique_recommendation_position"),
                    models.CheckConstraint(condition=models.Q(("position__gte", 0), ("position__lt", 8)), name="recommendation_position_under_8"),
                ],
            },
        ),
    ]
