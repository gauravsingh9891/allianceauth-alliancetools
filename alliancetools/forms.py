from django import forms


class AddJob(forms.Form):
    title = forms.CharField(label='Job Task', max_length=500)
    description = forms.CharField(label='Details', required=False, widget=forms.Textarea)


class AddComment(forms.Form):
    comment = forms.CharField(label='Comment', required=True, widget=forms.Textarea)
