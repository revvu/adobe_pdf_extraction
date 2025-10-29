import logging
import os
from datetime import datetime

import zipfile
import json

from adobe.pdfservices.operation.auth.service_principal_credentials import ServicePrincipalCredentials
from adobe.pdfservices.operation.exception.exceptions import ServiceApiException, ServiceUsageException, SdkException
from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
from adobe.pdfservices.operation.io.cloud_asset import CloudAsset
from adobe.pdfservices.operation.io.stream_asset import StreamAsset
from adobe.pdfservices.operation.pdf_services import PDFServices
from adobe.pdfservices.operation.pdfjobs.jobs.extract_pdf_job import ExtractPDFJob
from adobe.pdfservices.operation.pdfjobs.params.extract_pdf.extract_element_type import ExtractElementType
from adobe.pdfservices.operation.pdfjobs.params.extract_pdf.extract_pdf_params import ExtractPDFParams
from adobe.pdfservices.operation.pdfjobs.result.extract_pdf_result import ExtractPDFResult

from dotenv import load_dotenv
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO)



# This sample illustrates how to extract Text Information from PDF.
#
# Refer to README.md for instructions on how to run the samples & understand output zip file.

class ExtractTextInfoFromPDF:
    def __init__(self):
        try:
            # Stage 1: Load PDF file
            input_stream = self._load_pdf_file()
            
            # Stage 2: Initialize PDF Services client
            pdf_services = self._initialize_pdf_services()
            
            # Stage 3: Upload PDF to Adobe services
            input_asset = self._upload_pdf(pdf_services, input_stream)
            
            # Stage 4: Create and submit extraction job
            pdf_services_response = self._execute_extraction_job(pdf_services, input_asset)
            
            # Stage 5: Download extraction results
            output_file_path = self._download_results(pdf_services, pdf_services_response)
            
            # Stage 6: Process extracted data
            self._process_extracted_data(output_file_path)

        except (ServiceApiException, ServiceUsageException, SdkException) as e:
            logging.exception(f'Exception encountered while executing operation: {e}')

    def _load_pdf_file(self) -> bytes:
        """Stage 1: Load PDF file from disk."""
        with open('./extractPdfInput.pdf', 'rb') as file:
            return file.read()

    def _initialize_pdf_services(self) -> PDFServices:
        """Stage 2: Initialize PDF Services client with credentials."""
        credentials = ServicePrincipalCredentials(
            client_id=os.getenv('PDF_SERVICES_CLIENT_ID'),
            client_secret=os.getenv('PDF_SERVICES_CLIENT_SECRET')
        )
        return PDFServices(credentials=credentials)

    def _upload_pdf(self, pdf_services: PDFServices, input_stream: bytes):
        """Stage 3: Upload PDF to Adobe cloud services."""
        return pdf_services.upload(input_stream=input_stream, mime_type=PDFServicesMediaType.PDF)

    def _execute_extraction_job(self, pdf_services: PDFServices, input_asset):
        """Stage 4: Create and submit extraction job, then wait for results."""
        # Create parameters for the job
        extract_pdf_params = ExtractPDFParams(
            elements_to_extract=[ExtractElementType.TEXT],
        )

        # Create and submit job
        extract_pdf_job = ExtractPDFJob(input_asset=input_asset, extract_pdf_params=extract_pdf_params)
        location = pdf_services.submit(extract_pdf_job)
        
        # Get job result
        return pdf_services.get_job_result(location, ExtractPDFResult)

    def _download_results(self, pdf_services: PDFServices, pdf_services_response) -> str:
        """Stage 5: Download extraction results and save to disk."""
        # Get content from the resulting asset
        result_asset: CloudAsset = pdf_services_response.get_result().get_resource()
        stream_asset: StreamAsset = pdf_services.get_content(result_asset)

        # Save results to file
        output_file_path = self.create_output_file_path()
        with open(output_file_path, "wb") as file:
            file.write(stream_asset.get_input_stream())
        
        return output_file_path

    def _process_extracted_data(self, output_file_path: str):
        """Stage 6: Extract and process structured data from zip file."""
        # Open zip archive and read structuredData.json
        archive = zipfile.ZipFile(output_file_path, 'r')
        jsonentry = archive.open('structuredData.json')
        jsondata = jsonentry.read()
        data = json.loads(jsondata)
        archive.close()

        # Filter and print H1 headings
        for element in data["elements"]:
            if element["Path"].endswith("/H1"):
                print(element["Text"])

    # Generates a string containing a directory structure and file name for the output file
    @staticmethod
    def create_output_file_path() -> str:
        now = datetime.now()
        time_stamp = now.strftime("%Y-%m-%dT%H-%M-%S")
        os.makedirs("output/ExtractTextInfoFromPDF", exist_ok=True)
        return f"output/ExtractTextInfoFromPDF/extract{time_stamp}.zip"


if __name__ == "__main__":
    ExtractTextInfoFromPDF()
