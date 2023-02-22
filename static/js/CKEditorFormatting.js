// Overrides CKEditor's default behaviour that adds newlines after <p>, creating new <p> and new newlines after each
// edit.
// From: https://stackoverflow.com/questions/2547090/removing-unwanted-newline-characters-when-adding-p-in-ckeditor

CKEDITOR.replace( 'body',
{
    on :
    {
        instanceReady : function( ev )
        {
            // Output paragraphs as <p>Text</p>.
            this.dataProcessor.writer.setRules( 'p',
                {
                    indent : false,
                    breakBeforeOpen : false,
                    breakAfterOpen : false,
                    breakBeforeClose : false,
                    breakAfterClose : false
                });
            this.dataProcessor.writer.setRules( 'br',
                {
                    indent : false,
                    breakBeforeOpen : false,
                    breakAfterOpen : false,
                    breakBeforeClose : false,
                    breakAfterClose : false
                });
        }
    }
});