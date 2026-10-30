import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0006_post_publish_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='PostVersion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(blank=True, max_length=200)),
                ('size', models.PositiveIntegerField(default=0)),
                ('digest', models.CharField(max_length=64)),
                ('source', models.CharField(choices=[('edit', 'Edit'), ('restore', 'Before restore')], default='edit', max_length=10)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('post', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='versions', to='posts.post')),
            ],
            options={
                'ordering': ['-created_at', '-pk'],
                'indexes': [models.Index(fields=['post', '-created_at'], name='posts_postv_post_id_79211a_idx')],
            },
        ),
    ]
