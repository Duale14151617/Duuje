from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ranks", "0004_add_command_ranks"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rank",
            name="category",
            field=models.CharField(
                choices=[("enlisted", "Enlisted"), ("warrant", "Warrant"), ("officer", "Officer"),
                         ("unspecified", "Unspecified"), ("general_officer", "General Officer"),
                         ("senior_officer", "Senior Officer"), ("junior_officer", "Junior Officer"),
                         ("inspector", "Inspector"), ("nco", "Nco"), ("askari", "Askari")],
                max_length=16),
        ),
    ]
