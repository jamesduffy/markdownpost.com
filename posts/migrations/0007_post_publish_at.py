from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0006_tags'),
    ]

    operations = [
        migrations.AddField(
            model_name='post',
            name='publish_at',
            field=models.DateTimeField(blank=True, db_index=True, editable=False, null=True),
        ),
    ]
