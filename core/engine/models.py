from django.db import models

class ProductionKit(models.Model):
    topic = models.CharField(max_length=300)
    tone = models.CharField(max_length=50, default="cinematic")
    language = models.CharField(max_length=50, default="English")
    kit = models.JSONField()  # works with SQLite in modern Django
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.topic[:40]} ({self.created_at:%Y-%m-%d %H:%M})"