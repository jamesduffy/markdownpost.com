from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_show_related_posts'),
    ]

    operations = [
        migrations.AddField(model_name='user', name='theme', field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name='user', name='site_title', field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name='user', name='tagline', field=models.CharField(blank=True, max_length=140)),
        migrations.AddField(model_name='user', name='about_md', field=models.TextField(blank=True, max_length=5000)),
    ]
