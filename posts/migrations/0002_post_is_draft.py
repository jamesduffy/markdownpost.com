from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posts", "0001_initial")]

    operations = [
        # Everything that exists today was saved by its author, so it is not a draft...
        migrations.AddField(model_name="post", name="is_draft", field=models.BooleanField(default=False), preserve_default=False),
        # ...but posts created from now on start as drafts.
        migrations.AlterField(model_name="post", name="is_draft", field=models.BooleanField(default=True)),
    ]
