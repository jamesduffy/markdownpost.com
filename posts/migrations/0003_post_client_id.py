from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posts", "0002_post_is_draft"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.AddField(model_name="post", name="client_id", field=models.CharField(blank=True, editable=False, max_length=64, null=True)),
        migrations.AddConstraint(
            model_name="post",
            constraint=models.UniqueConstraint(fields=("author", "client_id"), name="unique_author_client_id"),
        ),
    ]
