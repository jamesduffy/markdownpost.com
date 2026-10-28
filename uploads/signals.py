from django.contrib.auth import get_user_model
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from posts import storage


@receiver(pre_delete, sender=get_user_model())
def delete_user_uploads(sender, instance, **kwargs):
    """Remove the user's image objects; the Upload rows go with the user via CASCADE."""
    for key in instance.uploads.values_list("key", flat=True):
        try:
            storage.get_storage().delete(key)
        except storage.StorageError:
            pass
